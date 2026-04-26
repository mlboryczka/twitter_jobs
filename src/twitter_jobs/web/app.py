"""FastAPI app factory — wires templates, static files, routes, auth."""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from twitter_jobs.web.routes import build_router

_WEB_DIR = Path(__file__).resolve().parent


def _x_text(value: str | None) -> str:
    """Decode HTML entities from X API tweet text (&amp; → &, &lt; → <, etc.).

    The X v2 API returns tweet text with HTML entity encoding applied; if we
    render it raw, Jinja escapes the already-encoded entities again and the
    user sees '&amp;' instead of '&'. Unescape once before letting Jinja do
    its normal autoescape pass.
    """
    if not value:
        return ""
    return html.unescape(value)


def create_app(lifespan: Callable[..., Any] | None = None) -> FastAPI:
    app = FastAPI(title="twitter_jobs", lifespan=lifespan)

    templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    templates.env.filters["x_text"] = _x_text
    app.mount(
        "/static",
        StaticFiles(directory=str(_WEB_DIR / "static")),
        name="static",
    )

    app.include_router(build_router(templates))

    return app
