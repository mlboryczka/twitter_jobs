"""Entrypoint — starts the FastAPI app and the APScheduler worker in one process.

Run with:

    uv run python -m twitter_jobs.main
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from twitter_jobs.config import get_settings
from twitter_jobs.scheduler import _safe_search_pull, build_scheduler
from twitter_jobs.web.app import create_app

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Scheduler started")
    # Kick off an initial pull shortly after boot — useful on cold start.
    scheduler.add_job(_safe_search_pull, id="search_pull_initial", replace_existing=True)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def build_app() -> FastAPI:
    _configure_logging()
    return create_app(lifespan=lifespan)


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "twitter_jobs.main:build_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
