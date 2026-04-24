"""Walk the last 7 days of tweets in the DB through the prefilter and print hit stats."""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from twitter_jobs.classify.prefilter import is_potential_job  # noqa: E402
from twitter_jobs.db.models import Tweet  # noqa: E402
from twitter_jobs.db.session import session_scope  # noqa: E402

SAMPLE_SIZE = 20


async def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with session_scope() as session:
        result = await session.execute(
            select(Tweet).options(joinedload(Tweet.author)).where(Tweet.created_at >= cutoff)
        )
        tweets = result.unique().scalars().all()

    hits: list[tuple[Tweet, list[str], list[str]]] = []
    misses: list[Tweet] = []
    for t in tweets:
        author = {
            "description": t.author.description if t.author else "",
            "username": t.author.username if t.author else "",
        }
        raw = dict(t.raw_json or {})
        raw.setdefault("text", t.text)
        raw.setdefault("referenced_tweets", t.referenced_tweets)
        result = is_potential_job(raw, author)
        if result.hit:
            hits.append((t, result.hiring_matches, result.role_matches))
        else:
            misses.append(t)

    total = len(tweets)
    hit_n = len(hits)
    pct = (hit_n / total * 100) if total else 0.0
    print(f"\nTotal tweets (last 7 days): {total}")
    print(f"Prefilter hits:             {hit_n} ({pct:.2f}%)\n")

    random.shuffle(hits)
    random.shuffle(misses)

    print("=== 20 random HITS ===")
    for t, hmatches, rmatches in hits[:SAMPLE_SIZE]:
        print(f"\n@{t.author.username} ({t.created_at:%Y-%m-%d}):")
        print(f"  hiring: {hmatches}")
        print(f"  roles:  {rmatches}")
        print(f"  text:   {t.text}")

    print("\n=== 20 random NON-HITS ===")
    for t in misses[:SAMPLE_SIZE]:
        print(f"\n@{t.author.username} ({t.created_at:%Y-%m-%d}):")
        print(f"  text:   {t.text}")


if __name__ == "__main__":
    asyncio.run(main())
