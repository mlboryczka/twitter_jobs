"""Shared ingestion helpers used by every X-API worker.

Spam heuristics, the prefilter+classifier pipeline that turns raw tweets into
job_postings, and low-level upsert/cursor helpers all live here so individual
workers contain only the query/pagination logic specific to their endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_jobs.classify.classifier import JobClassification, classify
from twitter_jobs.classify.industries import is_avoided
from twitter_jobs.classify.prefilter import (
    BIO_RECRUITER_PATTERNS,
    WEAK_HIRING_PATTERNS,
    is_potential_job,
)
from twitter_jobs.db.models import Author, JobPosting, Tweet, TweetSource, WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.ingest.threads import reconstruct_thread
from twitter_jobs.x_api.client import XClient
from twitter_jobs.x_api.types import XAuthor, XIncludes, XTweet

logger = logging.getLogger(__name__)

IMAGE_SHORT_TEXT_THRESHOLD = 140  # chars

# Minimum spacing between Anthropic classifier calls. The Haiku tier-1 limit
# is 50 RPM; 1.5s = 40 RPM keeps us comfortably under, so the SDK never has
# to retry on a 429. Bump up if you upgrade your Anthropic tier.
CLASSIFIER_MIN_INTERVAL_SEC = 1.5
_last_classify_call = 0.0

# Spam thresholds — below MIN_AUTHOR_FOLLOWERS we dismiss unless verified.
# The follow-back-farmer ratio catches accounts that aggressively follow and
# only get a small fraction back; we only apply it once `following` is high
# enough to be statistically meaningful.
MIN_AUTHOR_FOLLOWERS = 200
MIN_FOLLOWER_TO_FOLLOWING_RATIO = 0.1
MIN_FOLLOWING_FOR_RATIO_CHECK = 500

# Conservative bio patterns; the author is almost certainly not posting a real
# job. We only flag blatant cases — false positives erode user trust faster
# than false negatives waste a few cents of classifier spend.
SPAM_BIO_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\$\$\$+",
        r"\bcrypto signals?\b",
        r"\bget rich\b",
        r"\bmake money (?:fast|online)\b",
        r"\bearn \$\d",
        r"\bfollow.?(?:4|for).?follow\b",
        r"\bfollow.?back\b",
        r"\bdm (?:for|me for) (?:signals?|leads?|airdrops?|free)\b",
        r"\btelegram\.me/",
        r"\bonlyfans\b",
        r"\b18\+\b",
    ]
]


def spam_dismiss_reason(author: XAuthor) -> str | None:
    """Return a dismissal reason if the author looks like spam, else None.

    Order matters: we check the most precise signals first so the reason
    string is informative.
    """
    metrics = author.get("public_metrics") or {}
    followers = metrics.get("followers_count")
    following = metrics.get("following_count")
    verified = bool(author.get("verified", False))
    bio = (author.get("description") or "")

    # Bio red flags — apply unconditionally; verified doesn't excuse "DM for signals".
    for pat in SPAM_BIO_PATTERNS:
        m = pat.search(bio)
        if m:
            return f"auto: spam bio pattern ({m.group(0)!r})"

    # Verified accounts bypass the count-based heuristics — X verifies real people / orgs.
    if verified:
        return None

    # Follow-back farmer ratio.
    if (
        isinstance(followers, int)
        and isinstance(following, int)
        and following >= MIN_FOLLOWING_FOR_RATIO_CHECK
        and followers < following * MIN_FOLLOWER_TO_FOLLOWING_RATIO
    ):
        return (
            f"auto: follow-back farmer (follows {following}, only {followers} follow back)"
        )

    # Low-follower threshold.
    if isinstance(followers, int) and followers < MIN_AUTHOR_FOLLOWERS:
        return f"auto: low follower count ({followers} < {MIN_AUTHOR_FOLLOWERS})"

    return None


async def classify_new_tweets(
    client: XClient,
    data: list[XTweet],
    includes: XIncludes,
    new_ids: list[str],
) -> tuple[int, int]:
    """Run prefilter + classifier over newly-ingested tweets. Returns (jobs, manual_review)."""
    if not new_ids:
        return 0, 0

    users_by_id: dict[str, XAuthor] = {u["id"]: u for u in includes.get("users") or []}
    ref_tweets_by_id: dict[str, XTweet] = {t["id"]: t for t in includes.get("tweets") or []}

    jobs_inserted = 0
    manual_inserted = 0

    for t in data:
        if t["id"] not in new_ids:
            continue
        author: XAuthor = users_by_id.get(t.get("author_id", ""), {})

        spam_reason = spam_dismiss_reason(author)

        # --- image flagging: skip classifier, push to manual review ---
        if _should_flag_as_image(t, author, ref_tweets_by_id):
            await _insert_job_posting(
                tweet_id=t["id"],
                classification=JobClassification(
                    is_target=True,
                    role_category="unknown",
                    company=None,
                    location=None,
                    is_remote=None,
                    seniority=None,
                    apply_link=None,
                    industry="other",
                    is_us_eligible=None,
                    classifier_reasoning="Flagged for manual review: media attached with short caption + hiring signal. Classifier can't see images.",
                ),
                needs_manual_review=True,
                spam_reason=spam_reason,
            )
            manual_inserted += 1
            continue

        result = is_potential_job(t, author, includes_tweets_by_id=ref_tweets_by_id)
        if not result.hit:
            continue

        # Reconstruct thread if this is a head-of-thread.
        thread_tweets = [t]
        try:
            thread_tweets = await reconstruct_thread(client, t, author)
        except Exception:
            logger.exception("thread reconstruction failed, continuing with single tweet")

        await _throttle_classifier()
        classification = await classify(t, author, thread_tweets)
        if classification is None or not classification.is_target:
            continue

        await _insert_job_posting(
            tweet_id=t["id"],
            classification=classification,
            needs_manual_review=False,
            spam_reason=spam_reason,
        )
        jobs_inserted += 1

    return jobs_inserted, manual_inserted


async def _throttle_classifier() -> None:
    """Sleep until the minimum spacing between Anthropic calls has elapsed."""
    global _last_classify_call
    elapsed = time.monotonic() - _last_classify_call
    if elapsed < CLASSIFIER_MIN_INTERVAL_SEC:
        await asyncio.sleep(CLASSIFIER_MIN_INTERVAL_SEC - elapsed)
    _last_classify_call = time.monotonic()


def _should_flag_as_image(
    tweet: XTweet,
    author: XAuthor,
    ref_tweets_by_id: dict[str, XTweet],
) -> bool:
    """Tweet has media + short caption + some hiring signal → manual review."""
    attachments = tweet.get("attachments") or {}
    media_keys = attachments.get("media_keys") or []
    if not media_keys:
        return False

    text = tweet.get("text") or ""
    # If this is a retweet, the body lives on the referenced tweet, not the RT.
    for r in tweet.get("referenced_tweets") or []:
        if r.get("type") == "retweeted":
            src = ref_tweets_by_id.get(r.get("id", ""))
            if src and src.get("text"):
                text = src["text"]

    if len(text) > IMAGE_SHORT_TEXT_THRESHOLD:
        return False

    bio = author.get("description") or ""
    bio_recruiter = any(p.search(bio) for p in BIO_RECRUITER_PATTERNS)
    weak_hiring = any(p.search(text) for p in WEAK_HIRING_PATTERNS)
    return bio_recruiter or weak_hiring


async def _insert_job_posting(
    *,
    tweet_id: str,
    classification: JobClassification,
    needs_manual_review: bool,
    spam_reason: str | None = None,
) -> None:
    # Auto-dismiss in three cases — still inserted for transparency / later
    # re-classification, but never hits the inbox.
    if is_avoided(classification.industry):
        status = "dismissed"
        dismissal_reason = f"auto: avoided industry ({classification.industry})"
        status_changed_at = datetime.utcnow()
    elif classification.is_us_eligible is False:
        status = "dismissed"
        dismissal_reason = (
            f"auto: not US-eligible (location: {classification.location or 'unspecified'})"
        )
        status_changed_at = datetime.utcnow()
    elif spam_reason:
        status = "dismissed"
        dismissal_reason = spam_reason
        status_changed_at = datetime.utcnow()
    else:
        status = "new"
        dismissal_reason = None
        status_changed_at = None

    row = {
        "tweet_id": tweet_id,
        "role_category": classification.role_category,
        "company": classification.company,
        "location": classification.location,
        "is_remote": classification.is_remote,
        "seniority": classification.seniority,
        "apply_link": classification.apply_link,
        "industry": classification.industry,
        "is_us_eligible": classification.is_us_eligible,
        "classifier_reasoning": classification.classifier_reasoning,
        "needs_manual_review": needs_manual_review,
        "status": status,
        "dismissal_reason": dismissal_reason,
        "status_changed_at": status_changed_at,
    }
    async with session_scope() as session:
        await session.execute(
            pg_insert(JobPosting)
            .values(row)
            .on_conflict_do_nothing(index_elements=[JobPosting.tweet_id])
        )


async def write_worker_state(
    session: AsyncSession, key: str, value: dict[str, object]
) -> None:
    stmt = (
        pg_insert(WorkerState)
        .values(key=key, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value}
        )
    )
    await session.execute(stmt)


async def existing_tweet_ids(
    session: AsyncSession, ids: list[str]
) -> set[str]:
    if not ids:
        return set()
    res = await session.execute(select(Tweet.tweet_id).where(Tweet.tweet_id.in_(ids)))
    return {r for (r,) in res.all()}


async def upsert_page(
    session: AsyncSession,
    tweets: list[XTweet],
    includes: XIncludes,
    *,
    source_type: str = "feed",
) -> int:
    users = {u["id"]: u for u in includes.get("users", [])}

    if users:
        author_rows = [
            {
                "author_id": u["id"],
                "username": u.get("username", ""),
                "name": u.get("name", ""),
                "description": u.get("description"),
                "verified": bool(u.get("verified", False)),
                "public_metrics": u.get("public_metrics") or {},
            }
            for u in users.values()
        ]
        await session.execute(
            pg_insert(Author)
            .values(author_rows)
            .on_conflict_do_update(
                index_elements=[Author.author_id],
                set_={
                    "username": pg_insert(Author).excluded.username,
                    "name": pg_insert(Author).excluded.name,
                    "description": pg_insert(Author).excluded.description,
                    "verified": pg_insert(Author).excluded.verified,
                    "public_metrics": pg_insert(Author).excluded.public_metrics,
                },
            )
        )

    if not tweets:
        return 0

    existing = await session.execute(
        select(Tweet.tweet_id).where(Tweet.tweet_id.in_([t["id"] for t in tweets]))
    )
    existing_ids = {r for (r,) in existing.all()}

    tweet_rows = []
    for t in tweets:
        tweet_rows.append(
            {
                "tweet_id": t["id"],
                "author_id": t.get("author_id") or "",
                "text": t.get("text", ""),
                "created_at": _parse_x_ts(t.get("created_at")),
                "lang": t.get("lang"),
                "public_metrics": t.get("public_metrics") or {},
                "entities": t.get("entities"),
                "conversation_id": t.get("conversation_id"),
                "in_reply_to_user_id": t.get("in_reply_to_user_id"),
                "referenced_tweets": t.get("referenced_tweets"),
                "raw_json": t,
            }
        )
    await session.execute(
        pg_insert(Tweet)
        .values(tweet_rows)
        .on_conflict_do_nothing(index_elements=[Tweet.tweet_id])
    )

    source_rows = [{"tweet_id": t["id"], "source_type": source_type} for t in tweets]
    await session.execute(
        pg_insert(TweetSource)
        .values(source_rows)
        .on_conflict_do_nothing(
            index_elements=[TweetSource.tweet_id, TweetSource.source_type]
        )
    )

    new_count = sum(1 for t in tweets if t["id"] not in existing_ids)
    return new_count


def id_gt(a: str, b: str) -> bool:
    """Compare two snowflake-style numeric string IDs without int overflow.

    Tweet IDs are kept as strings because they exceed JS Number range; this
    helper does the comparison the way the X API would on the server side.
    """
    if len(a) != len(b):
        return len(a) > len(b)
    return a > b


def _parse_x_ts(value: str | None) -> datetime | None:
    """Parse X's ISO-8601 timestamp (e.g. '2026-04-25T22:40:34.000Z')."""
    if value is None:
        return None
    return datetime.fromisoformat(value)
