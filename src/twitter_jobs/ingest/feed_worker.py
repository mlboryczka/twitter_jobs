"""Home-timeline feed worker — paginated pulls, upserts, cursor state, classification dispatch."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

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
from twitter_jobs.config import get_settings
from twitter_jobs.db.models import ApiCall, Author, JobPosting, Tweet, TweetSource, WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.ingest.threads import reconstruct_thread
from twitter_jobs.x_api.auth import XAuth
from twitter_jobs.x_api.client import XClient
from twitter_jobs.x_api.endpoints import get_home_timeline

logger = logging.getLogger(__name__)

FEED_SINCE_ID_KEY = "feed_since_id"
LAST_PULL_SUMMARY_KEY = "feed_last_pull_summary"
MAX_PAGES_PER_RUN = 10
IMAGE_SHORT_TEXT_THRESHOLD = 140  # chars


async def run_feed_pull() -> dict[str, Any]:
    """Pull new tweets from the home timeline since the last cursor, classify hits."""
    settings = get_settings()
    if not settings.x_user_numeric_id:
        raise RuntimeError("X_USER_NUMERIC_ID must be set for the feed worker.")

    auth = XAuth(settings=settings)

    async with session_scope() as session:
        since_id = await _read_since_id(session)
    logger.info("feed_pull starting since_id=%s", since_id)

    pages = 0
    new_tweets_total = 0
    api_calls_total = 0
    newest_id_seen = since_id
    next_token: str | None = None
    jobs_inserted = 0
    manual_review_inserted = 0

    async with XClient(auth) as client:
        while True:
            pages += 1
            if pages > MAX_PAGES_PER_RUN:
                logger.warning(
                    "feed_pull hit MAX_PAGES_PER_RUN=%d, stopping", MAX_PAGES_PER_RUN
                )
                break

            payload = await get_home_timeline(
                client,
                user_id=settings.x_user_numeric_id,
                since_id=since_id,
                next_token=next_token,
                max_results=100,
            )
            data = payload.get("data") or []
            includes = payload.get("includes") or {}
            meta = payload.get("meta") or {}
            api_calls_total += 1

            if not data:
                logger.info("feed_pull page %d: empty, done", pages)
                break

            async with session_scope() as session:
                existing_ids = await _existing_tweet_ids(session, [t["id"] for t in data])
                inserted = await _upsert_page(session, data, includes)

            new_ids = [t["id"] for t in data if t["id"] not in existing_ids]
            new_tweets_total += inserted
            page_newest = meta.get("newest_id")
            if page_newest and (
                newest_id_seen is None or _id_gt(page_newest, newest_id_seen)
            ):
                newest_id_seen = page_newest

            # Classify only the newly-ingested tweets in this page.
            jobs, manual = await _classify_new(client, data, includes, new_ids)
            jobs_inserted += jobs
            manual_review_inserted += manual

            if inserted == 0:
                logger.info(
                    "feed_pull page %d: 0 new tweets, stopping pagination", pages
                )
                break

            next_token = meta.get("next_token")
            if not next_token:
                break

    async with session_scope() as session:
        cost_total = await _sum_recent_cost(session, pages)
        if newest_id_seen and newest_id_seen != since_id:
            await _write_since_id(session, newest_id_seen)
        summary = {
            "new_tweets": new_tweets_total,
            "api_calls": api_calls_total,
            "cost_usd": cost_total,
            "pages": pages,
            "jobs_inserted": jobs_inserted,
            "manual_review_inserted": manual_review_inserted,
            "ran_at": datetime.utcnow().isoformat() + "Z",
        }
        await _write_worker_state(session, LAST_PULL_SUMMARY_KEY, summary)

    logger.info("feed_pull done: %s", summary)
    return summary


async def _classify_new(
    client: XClient,
    data: list[dict[str, Any]],
    includes: dict[str, Any],
    new_ids: list[str],
) -> tuple[int, int]:
    """Run prefilter + classifier over newly-ingested tweets. Returns (jobs, manual_review)."""
    if not new_ids:
        return 0, 0

    users_by_id = {u["id"]: u for u in includes.get("users") or []}
    ref_tweets_by_id = {t["id"]: t for t in includes.get("tweets") or []}

    jobs_inserted = 0
    manual_inserted = 0

    for t in data:
        if t["id"] not in new_ids:
            continue
        author = users_by_id.get(t.get("author_id", ""), {}) or {}

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
                    classifier_reasoning="Flagged for manual review: media attached with short caption + hiring signal. Classifier can't see images.",
                ),
                needs_manual_review=True,
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

        classification = await classify(t, author, thread_tweets)
        if classification is None or not classification.is_target:
            continue

        await _insert_job_posting(
            tweet_id=t["id"],
            classification=classification,
            needs_manual_review=False,
        )
        jobs_inserted += 1

    return jobs_inserted, manual_inserted


def _should_flag_as_image(
    tweet: dict[str, Any],
    author: dict[str, Any],
    ref_tweets_by_id: dict[str, dict[str, Any]],
) -> bool:
    """Tweet has media + short caption + some hiring signal → manual review."""
    attachments = tweet.get("attachments") or {}
    media_keys = attachments.get("media_keys") or []
    if not media_keys:
        return False

    text = tweet.get("text") or ""
    # unwrap retweet
    for r in tweet.get("referenced_tweets") or []:
        if r.get("type") == "retweeted":
            src = ref_tweets_by_id.get(r.get("id", ""))
            if src and src.get("text"):
                text = src["text"]

    if len(text) > IMAGE_SHORT_TEXT_THRESHOLD:
        return False

    bio = (author or {}).get("description") or ""
    bio_recruiter = any(p.search(bio) for p in BIO_RECRUITER_PATTERNS)
    weak_hiring = any(p.search(text) for p in WEAK_HIRING_PATTERNS)
    return bio_recruiter or weak_hiring


async def _insert_job_posting(
    *,
    tweet_id: str,
    classification: JobClassification,
    needs_manual_review: bool,
) -> None:
    # Auto-dismiss postings in avoided industries — still inserted for
    # transparency / re-classification later, but never hits the inbox.
    if is_avoided(classification.industry):
        status = "dismissed"
        dismissal_reason = f"auto: avoided industry ({classification.industry})"
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


async def _read_since_id(session: AsyncSession) -> str | None:
    row = await session.get(WorkerState, FEED_SINCE_ID_KEY)
    if row is None:
        return None
    return row.value.get("since_id")


async def _write_since_id(session: AsyncSession, since_id: str) -> None:
    await _write_worker_state(session, FEED_SINCE_ID_KEY, {"since_id": since_id})


async def _write_worker_state(
    session: AsyncSession, key: str, value: dict[str, Any]
) -> None:
    stmt = (
        pg_insert(WorkerState)
        .values(key=key, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value}
        )
    )
    await session.execute(stmt)


async def _sum_recent_cost(session: AsyncSession, n_pages: int) -> float:
    if n_pages <= 0:
        return 0.0
    result = await session.execute(
        select(ApiCall.cost_usd).order_by(ApiCall.id.desc()).limit(n_pages)
    )
    return float(sum(row for row in result.scalars()))


async def _existing_tweet_ids(
    session: AsyncSession, ids: list[str]
) -> set[str]:
    if not ids:
        return set()
    res = await session.execute(select(Tweet.tweet_id).where(Tweet.tweet_id.in_(ids)))
    return {r for (r,) in res.all()}


async def _upsert_page(
    session: AsyncSession,
    tweets: list[dict[str, Any]],
    includes: dict[str, Any],
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


def _id_gt(a: str, b: str) -> bool:
    if len(a) != len(b):
        return len(a) > len(b)
    return a > b


def _parse_x_ts(value: str | None) -> datetime | None:
    """Parse X's ISO-8601 timestamp (e.g. '2026-04-25T22:40:34.000Z') to datetime."""
    if value is None:
        return None
    # Python 3.11+ accepts the trailing 'Z' directly.
    return datetime.fromisoformat(value)


async def get_last_pull_summary() -> dict[str, Any] | None:
    async with session_scope() as session:
        row = await session.get(WorkerState, LAST_PULL_SUMMARY_KEY)
        return row.value if row else None
