"""Export 50 random prefilter-hit tweets with empty label fields for manual labeling.

Usage: uv run python scripts/build_eval_set.py [path]

Writes a JSON array; each entry has the tweet text, author, metadata, and empty
fields you fill in by hand. Use the resulting file to spot-check the classifier
or to regression-test prompt changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from twitter_jobs.classify.prefilter import is_potential_job  # noqa: E402
from twitter_jobs.db.models import Tweet  # noqa: E402
from twitter_jobs.db.session import session_scope  # noqa: E402

SAMPLE_SIZE = 50


async def main(out: Path) -> None:
    async with session_scope() as session:
        tweets = (
            await session.execute(
                select(Tweet).options(joinedload(Tweet.author))
            )
        ).unique().scalars().all()

    hits = []
    for t in tweets:
        raw = dict(t.raw_json or {})
        raw.setdefault("id", t.tweet_id)
        raw.setdefault("text", t.text)
        raw.setdefault("referenced_tweets", t.referenced_tweets)
        author = {
            "description": t.author.description if t.author else "",
            "username": t.author.username if t.author else "",
        }
        if is_potential_job(raw, author).hit:
            hits.append(t)

    random.shuffle(hits)
    chosen = hits[:SAMPLE_SIZE]

    payload = []
    for t in chosen:
        payload.append(
            {
                "tweet_id": t.tweet_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "author_username": t.author.username if t.author else "",
                "author_bio": t.author.description if t.author else "",
                "text": t.text,
                # manual label fields — fill these in:
                "label_is_target": None,
                "label_role_category": None,
                "label_seniority": None,
                "notes": "",
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"wrote {len(payload)} entries to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    default = Path("eval_sets") / f"eval_set_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    ap.add_argument("path", nargs="?", type=Path, default=default)
    args = ap.parse_args()
    asyncio.run(main(args.path))
