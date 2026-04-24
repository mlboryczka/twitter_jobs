"""FastAPI app factory — wires templates, static files, routes, auth."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from twitter_jobs.ingest.feed_worker import get_last_pull_summary
from twitter_jobs.web.routes import build_router

_WEB_DIR = Path(__file__).resolve().parent


def create_app(lifespan: Callable[..., Any] | None = None) -> FastAPI:
    app = FastAPI(title="twitter_jobs", lifespan=lifespan)

    templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(_WEB_DIR / "static")),
        name="static",
    )

    app.include_router(build_router(templates))

    @app.get("/debug/last-pull")
    async def debug_last_pull() -> dict[str, Any]:
        """Temporary — removed in Phase 7."""
        return await get_last_pull_summary() or {"status": "no runs yet"}

    return app
