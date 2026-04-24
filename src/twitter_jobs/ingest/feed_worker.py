"""Home-timeline feed worker — paginated pulls, upserts, cursor state.

In Phase 5 this module will also dispatch classification. For now it only
ingests and records sources.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_jobs.config import get_settings
from twitter_jobs.db.models import ApiCall, Author, Tweet, TweetSource, WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.x_api.auth import XAuth
from twitter_jobs.x_api.client import XClient
from twitter_jobs.x_api.endpoints import get_home_timeline

logger = logging.getLogger(__name__)

FEED_SINCE_ID_KEY = "feed_since_id"
LAST_PULL_SUMMARY_KEY = "feed_last_pull_summary"
MAX_PAGES_PER_RUN = 10  # safety cap so a runaway call can't blow through budget


async def run_feed_pull() -> dict[str, Any]:
    """Pull new tweets from the home timeline since the last cursor.

    Returns a summary dict: {new_tweets, api_calls, cost_usd, pages}.
    """
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
    cost_total = 0.0
    newest_id_seen = since_id
    next_token: str | None = None

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
                inserted = await _upsert_page(session, data, includes)

            new_tweets_total += inserted
            # Track the newest tweet id for cursor update.
            page_newest = meta.get("newest_id")
            if page_newest and (
                newest_id_seen is None or _id_gt(page_newest, newest_id_seen)
            ):
                newest_id_seen = page_newest

            # Early exit: nothing in this page was new.
            if inserted == 0:
                logger.info(
                    "feed_pull page %d: 0 new tweets, stopping pagination", pages
                )
                break

            next_token = meta.get("next_token")
            if not next_token:
                break

    # Best-effort cost total from api_calls we just inserted.
    async with session_scope() as session:
        cost_total = await _sum_recent_cost(session, pages)
        if newest_id_seen and newest_id_seen != since_id:
            await _write_since_id(session, newest_id_seen)
        summary = {
            "new_tweets": new_tweets_total,
            "api_calls": api_calls_total,
            "cost_usd": cost_total,
            "pages": pages,
            "ran_at": datetime.utcnow().isoformat() + "Z",
        }
        await _write_worker_state(session, LAST_PULL_SUMMARY_KEY, summary)

    logger.info("feed_pull done: %s", summary)
    return summary


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
    """Sum the cost_usd of the last n_pages api_calls rows (best-effort)."""
    if n_pages <= 0:
        return 0.0
    result = await session.execute(
        select(ApiCall.cost_usd)
        .order_by(ApiCall.id.desc())
        .limit(n_pages)
    )
    return float(sum(row for row in result.scalars()))


async def _upsert_page(
    session: AsyncSession,
    tweets: list[dict[str, Any]],
    includes: dict[str, Any],
) -> int:
    """Upsert one page of tweets + authors + source rows. Returns new-tweet count."""
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
                "created_at": t.get("created_at"),
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

    source_rows = [{"tweet_id": t["id"], "source_type": "feed"} for t in tweets]
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
    """Lexicographic comparison is incorrect for different-length numeric ids;
    compare by length first, then lexicographically."""
    if len(a) != len(b):
        return len(a) > len(b)
    return a > b


async def get_last_pull_summary() -> dict[str, Any] | None:
    async with session_scope() as session:
        row = await session.get(WorkerState, LAST_PULL_SUMMARY_KEY)
        return row.value if row else None
