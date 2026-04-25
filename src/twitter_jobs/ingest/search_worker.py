"""Search-based worker — runs a fixed set of role-targeted X search queries.

Designed for users whose home timeline isn't a high-density source of jobs
in their target roles. Each query is paginated independently, with a per-query
since_id cursor stored in worker_state. Tweets are deduplicated across queries
by primary key on the tweets table, then run through the same prefilter +
classifier pipeline as the home-timeline worker.

Costs are bounded by:
  - MAX_PAGES_PER_QUERY (per-query pagination cap)
  - SEARCH_MAX_RESULTS (page size)

Edit QUERIES below to add/remove searches.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from twitter_jobs.db.models import WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.ingest.feed_worker import (
    _classify_new,
    _existing_tweet_ids,
    _id_gt,
    _upsert_page,
    _write_worker_state,
)
from twitter_jobs.x_api.auth import XAuth
from twitter_jobs.x_api.client import XClient
from twitter_jobs.x_api.endpoints import search_recent
from twitter_jobs.config import get_settings

logger = logging.getLogger(__name__)

QUERIES = [
    '"corp dev" hiring -is:retweet lang:en',
    '"corporate development" hiring -is:retweet lang:en',
    '"chief of staff" hiring -is:retweet lang:en',
    '"strategic finance" (hiring OR "we\'re hiring" OR "open role") -is:retweet lang:en',
    '("corp strategy" OR "corporate strategy") hiring -is:retweet lang:en',
    '"business development" hiring -is:retweet -"sales rep" -SDR -AE lang:en',
    '"business operations" hiring -is:retweet lang:en',
    '("head of strategy" OR "VP strategy") hiring -is:retweet lang:en',
    '("head of ops" OR "head of operations" OR "VP operations") hiring -is:retweet lang:en',
    '"M&A" associate hiring -is:retweet lang:en',
]

SEARCH_SINCE_ID_PREFIX = "search_since_id:"
LAST_PULL_SUMMARY_KEY = "search_last_pull_summary"
MAX_PAGES_PER_QUERY = 2
SEARCH_MAX_RESULTS = 50


async def run_search_pull() -> dict[str, Any]:
    """Run every query in QUERIES, dedupe + classify, return a summary."""
    settings = get_settings()
    auth = XAuth(settings=settings)

    pages_total = 0
    api_calls_total = 0
    new_tweets_total = 0
    jobs_inserted = 0
    manual_review_inserted = 0
    per_query: list[dict[str, Any]] = []

    async with XClient(auth) as client:
        for idx, query in enumerate(QUERIES):
            since_id_key = f"{SEARCH_SINCE_ID_PREFIX}{idx}"
            async with session_scope() as session:
                row = await session.get(WorkerState, since_id_key)
                since_id = row.value.get("since_id") if row else None

            logger.info("search query [%d] starting since_id=%s q=%r", idx, since_id, query)

            pages = 0
            new_for_query = 0
            jobs_for_query = 0
            manual_for_query = 0
            newest_id_seen = since_id
            next_token: str | None = None

            while True:
                pages += 1
                if pages > MAX_PAGES_PER_QUERY:
                    logger.warning(
                        "search query [%d] hit MAX_PAGES_PER_QUERY=%d", idx, MAX_PAGES_PER_QUERY
                    )
                    break

                payload = await search_recent(
                    client,
                    query,
                    since_id=since_id,
                    next_token=next_token,
                    max_results=SEARCH_MAX_RESULTS,
                )
                api_calls_total += 1
                pages_total += 1

                data = payload.get("data") or []
                includes = payload.get("includes") or {}
                meta = payload.get("meta") or {}

                if not data:
                    logger.info("search query [%d] page %d: empty, done", idx, pages)
                    break

                async with session_scope() as session:
                    existing_ids = await _existing_tweet_ids(
                        session, [t["id"] for t in data]
                    )
                    inserted = await _upsert_page(
                        session, data, includes, source_type="search"
                    )

                new_ids = [t["id"] for t in data if t["id"] not in existing_ids]
                jobs, manual = await _classify_new(client, data, includes, new_ids)
                jobs_for_query += jobs
                manual_for_query += manual

                new_for_query += inserted
                page_newest = meta.get("newest_id")
                if page_newest and (
                    newest_id_seen is None or _id_gt(page_newest, newest_id_seen)
                ):
                    newest_id_seen = page_newest

                next_token = meta.get("next_token")
                if not next_token:
                    break

            new_tweets_total += new_for_query
            jobs_inserted += jobs_for_query
            manual_review_inserted += manual_for_query

            if newest_id_seen and newest_id_seen != since_id:
                async with session_scope() as session:
                    await _write_worker_state(
                        session, since_id_key, {"since_id": newest_id_seen}
                    )

            per_query.append({
                "idx": idx,
                "query": query,
                "pages": pages - 1 if pages > MAX_PAGES_PER_QUERY else pages,
                "new_tweets": new_for_query,
                "jobs": jobs_for_query,
                "manual": manual_for_query,
            })

    summary = {
        "queries_run": len(QUERIES),
        "pages": pages_total,
        "api_calls": api_calls_total,
        "new_tweets": new_tweets_total,
        "jobs_inserted": jobs_inserted,
        "manual_review_inserted": manual_review_inserted,
        "per_query": per_query,
        "ran_at": datetime.utcnow().isoformat() + "Z",
    }
    async with session_scope() as session:
        await _write_worker_state(session, LAST_PULL_SUMMARY_KEY, summary)
    logger.info("search_pull done: %s", summary)
    return summary
