"""APScheduler setup — schedules the feed-pull worker and any future jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from twitter_jobs.config import get_settings
from twitter_jobs.ingest.feed_worker import run_feed_pull

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _safe_feed_pull,
        trigger=IntervalTrigger(seconds=settings.feed_pull_interval),
        id="feed_pull",
        name="X home timeline pull",
        max_instances=1,
        coalesce=True,
        next_run_time=None,  # first run is triggered on startup via main.py
    )
    return scheduler


async def _safe_feed_pull() -> None:
    try:
        await run_feed_pull()
    except Exception:  # pragma: no cover
        logger.exception("feed_pull job crashed")
