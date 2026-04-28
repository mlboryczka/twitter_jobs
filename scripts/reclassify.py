"""Re-run the classifier over prefilter-hit tweets in the DB.

Useful when iterating on the prompt. Does not re-pull from X. Only reclassifies
tweets whose prefilter currently fires (so irrelevant tweets don't burn tokens).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from twitter_jobs.classify.classifier import classify  # noqa: E402
from twitter_jobs.classify.industries import is_avoided  # noqa: E402
from twitter_jobs.classify.prefilter import is_potential_job  # noqa: E402
from twitter_jobs.db.models import JobPosting, Tweet  # noqa: E402
from twitter_jobs.db.session import session_scope  # noqa: E402
from twitter_jobs.ingest.common import spam_dismiss_reason  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("reclassify")


async def main(limit: int | None, throttle: float, skip_classified: bool) -> None:
    async with session_scope() as session:
        q = select(Tweet).options(joinedload(Tweet.author)).order_by(Tweet.created_at.desc())
        if limit:
            q = q.limit(limit)
        tweets = (await session.execute(q)).unique().scalars().all()

    logger.info("loaded %d tweets from DB", len(tweets))

    already_classified: set[str] = set()
    if skip_classified:
        async with session_scope() as session:
            res = await session.execute(
                select(JobPosting.tweet_id).where(JobPosting.industry.isnot(None))
            )
            already_classified = {tid for (tid,) in res.all()}
        logger.info("skipping %d tweets that already have an industry", len(already_classified))

    hits = []
    for t in tweets:
        if t.tweet_id in already_classified:
            continue
        raw = dict(t.raw_json or {})
        raw.setdefault("id", t.tweet_id)
        raw.setdefault("text", t.text)
        raw.setdefault("referenced_tweets", t.referenced_tweets)
        author = _author_dict(t)
        result = is_potential_job(raw, author)
        if result.hit:
            hits.append((t, raw, author))

    logger.info("prefilter hits: %d (throttle=%.2fs/call)", len(hits), throttle)

    reclassified = 0
    last_call = 0.0
    for i, (t, raw, author) in enumerate(hits, 1):
        # Spread calls so we don't constantly bounce off Anthropic rate limits.
        elapsed = time.monotonic() - last_call
        if elapsed < throttle:
            await asyncio.sleep(throttle - elapsed)
        last_call = time.monotonic()
        classification = await classify(raw, author, [raw])
        if classification is None:
            logger.info("[%d/%d] classifier returned None — skipping", i, len(hits))
            continue
        verdict = (
            f"target={classification.role_category}/{classification.industry}"
            if classification.is_target
            else "not-target"
        )
        logger.info("[%d/%d] %s — %s", i, len(hits), t.tweet_id, verdict)
        async with session_scope() as session:
            if not classification.is_target:
                # No longer a target — drop only if user hasn't triaged it.
                from sqlalchemy import and_
                await session.execute(
                    delete(JobPosting).where(
                        and_(
                            JobPosting.tweet_id == t.tweet_id,
                            JobPosting.status == "new",
                        )
                    )
                )
                continue

            avoided = is_avoided(classification.industry)
            us_blocked = classification.is_us_eligible is False
            spam_reason = spam_dismiss_reason(author)
            insert_values = dict(
                tweet_id=t.tweet_id,
                role_category=classification.role_category,
                company=classification.company,
                location=classification.location,
                is_remote=classification.is_remote,
                seniority=classification.seniority,
                apply_link=classification.apply_link,
                industry=classification.industry,
                is_us_eligible=classification.is_us_eligible,
                classifier_reasoning=classification.classifier_reasoning,
                needs_manual_review=False,
            )
            if avoided or us_blocked or spam_reason:
                from datetime import datetime, timezone
                insert_values["status"] = "dismissed"
                if avoided:
                    insert_values["dismissal_reason"] = (
                        f"auto: avoided industry ({classification.industry})"
                    )
                elif us_blocked:
                    insert_values["dismissal_reason"] = (
                        f"auto: not US-eligible (location: {classification.location or 'unspecified'})"
                    )
                else:
                    insert_values["dismissal_reason"] = spam_reason
                insert_values["status_changed_at"] = datetime.now(timezone.utc)

            stmt = pg_insert(JobPosting).values(**insert_values)
            # Update only classifier-derived fields on conflict; preserve the
            # user's status, dismissal_reason, status_changed_at, user_feedback.
            update_set = {
                "role_category": stmt.excluded.role_category,
                "company": stmt.excluded.company,
                "location": stmt.excluded.location,
                "is_remote": stmt.excluded.is_remote,
                "seniority": stmt.excluded.seniority,
                "apply_link": stmt.excluded.apply_link,
                "industry": stmt.excluded.industry,
                "is_us_eligible": stmt.excluded.is_us_eligible,
                "classifier_reasoning": stmt.excluded.classifier_reasoning,
                "needs_manual_review": stmt.excluded.needs_manual_review,
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=[JobPosting.tweet_id],
                set_=update_set,
            )
            await session.execute(stmt)

            # If this row's classification now puts it in an avoided bucket,
            # flip status to 'dismissed' — but only if the user hasn't
            # already triaged it manually.
            if avoided or us_blocked or spam_reason:
                from datetime import datetime, timezone
                from sqlalchemy import update as sa_update
                if avoided:
                    reason = f"auto: avoided industry ({classification.industry})"
                elif us_blocked:
                    reason = f"auto: not US-eligible (location: {classification.location or 'unspecified'})"
                else:
                    reason = spam_reason
                await session.execute(
                    sa_update(JobPosting)
                    .where(
                        (JobPosting.tweet_id == t.tweet_id)
                        & (JobPosting.status == "new")
                    )
                    .values(
                        status="dismissed",
                        dismissal_reason=reason,
                        status_changed_at=datetime.now(timezone.utc),
                    )
                )

            reclassified += 1
    logger.info("reclassified %d tweets as target", reclassified)


def _author_dict(tweet: Tweet) -> dict:
    a = tweet.author
    if a is None:
        return {}
    return {
        "username": a.username,
        "name": a.name,
        "description": a.description,
        "verified": a.verified,
        "public_metrics": a.public_metrics,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max tweets to consider (most recent first)")
    ap.add_argument("--throttle", type=float, default=1.5, help="min seconds between classifier calls (default 1.5 = ~40/min, safe under Anthropic free-tier limits)")
    ap.add_argument("--skip-classified", action="store_true", help="skip tweets that already have an industry tagged")
    args = ap.parse_args()
    asyncio.run(main(limit=args.limit, throttle=args.throttle, skip_classified=args.skip_classified))
