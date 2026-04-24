"""Re-run the classifier over prefilter-hit tweets in the DB.

Useful when iterating on the prompt. Does not re-pull from X. Only reclassifies
tweets whose prefilter currently fires (so irrelevant tweets don't burn tokens).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from twitter_jobs.classify.classifier import classify  # noqa: E402
from twitter_jobs.classify.prefilter import is_potential_job  # noqa: E402
from twitter_jobs.db.models import JobPosting, Tweet  # noqa: E402
from twitter_jobs.db.session import session_scope  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("reclassify")


async def main(limit: int | None) -> None:
    async with session_scope() as session:
        q = select(Tweet).options(joinedload(Tweet.author)).order_by(Tweet.created_at.desc())
        if limit:
            q = q.limit(limit)
        tweets = (await session.execute(q)).unique().scalars().all()

    logger.info("loaded %d tweets from DB", len(tweets))

    hits = []
    for t in tweets:
        raw = dict(t.raw_json or {})
        raw.setdefault("id", t.tweet_id)
        raw.setdefault("text", t.text)
        raw.setdefault("referenced_tweets", t.referenced_tweets)
        author = _author_dict(t)
        result = is_potential_job(raw, author)
        if result.hit:
            hits.append((t, raw, author))

    logger.info("prefilter hits: %d", len(hits))

    reclassified = 0
    for t, raw, author in hits:
        classification = await classify(raw, author, [raw])
        if classification is None:
            continue
        async with session_scope() as session:
            await session.execute(delete(JobPosting).where(JobPosting.tweet_id == t.tweet_id))
            if classification.is_target:
                await session.execute(
                    pg_insert(JobPosting).values(
                        tweet_id=t.tweet_id,
                        role_category=classification.role_category,
                        company=classification.company,
                        location=classification.location,
                        is_remote=classification.is_remote,
                        seniority=classification.seniority,
                        apply_link=classification.apply_link,
                        classifier_reasoning=classification.classifier_reasoning,
                        needs_manual_review=False,
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
    args = ap.parse_args()
    asyncio.run(main(limit=args.limit))
