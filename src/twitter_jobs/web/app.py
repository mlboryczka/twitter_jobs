"""FastAPI app factory.

Phase 3 ships a minimal app with just a /debug endpoint. Phase 6 adds the
dashboard routes, templates, auth, and static files.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from twitter_jobs.ingest.feed_worker import get_last_pull_summary


def create_app(lifespan: Callable[..., Any] | None = None) -> FastAPI:
    app = FastAPI(title="twitter_jobs", lifespan=lifespan)

    @app.get("/debug/last-pull")
    async def debug_last_pull() -> dict[str, Any]:
        """Temporary — shows last feed-pull summary. Removed in Phase 7."""
        return await get_last_pull_summary() or {"status": "no runs yet"}

    return app
