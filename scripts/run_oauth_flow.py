"""One-shot OAuth 2.0 PKCE flow — captures a refresh token for the logged-in X account.

Run this on your local machine (not the VPS):

    uv run python scripts/run_oauth_flow.py

It starts a local HTTP server on 127.0.0.1:8765, prints an authorize URL, waits
for the redirect with ?code=..., exchanges the code for tokens, and prints the
refresh token. Copy the refresh token into your VPS ``.env`` as
``X_REFRESH_TOKEN``.

Uses scopes: tweet.read users.read bookmark.read offline.access.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets as _secrets
import sys
import urllib.parse
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from uvicorn import Config, Server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twitter_jobs.config import get_settings  # noqa: E402
from twitter_jobs.x_api.auth import AUTHORIZE_URL, SCOPES, TOKEN_URL  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("oauth_flow")


def _make_pkce() -> tuple[str, str]:
    verifier = (
        base64.urlsafe_b64encode(_secrets.token_bytes(64))
        .decode()
        .rstrip("=")
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


async def main() -> None:
    settings = get_settings()
    if not settings.x_client_id or not settings.x_client_secret:
        sys.exit("X_CLIENT_ID and X_CLIENT_SECRET must be set in .env before running.")

    verifier, challenge = _make_pkce()
    state = _secrets.token_urlsafe(16)

    authorize_params = {
        "response_type": "code",
        "client_id": settings.x_client_id,
        "redirect_uri": settings.x_redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(authorize_params)}"

    logger.info("\n=== X OAuth PKCE flow ===")
    logger.info("Open this URL in your browser (log in to X first):\n")
    logger.info("    %s\n", authorize_url)
    logger.info("Waiting for callback at %s ...", settings.x_redirect_uri)

    app = FastAPI()
    done = asyncio.Event()
    result: dict[str, str] = {}

    @app.get("/callback")
    async def callback(request: Request) -> dict[str, str]:
        qp = request.query_params
        if qp.get("state") != state:
            return {"error": "state mismatch"}
        if "code" not in qp:
            return {"error": "no code"}
        result["code"] = qp["code"]
        done.set()
        return {"ok": "You can close this tab."}

    # Bind to the exact host/port declared in X_REDIRECT_URI.
    parsed = urllib.parse.urlparse(settings.x_redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765

    config = Config(app=app, host=host, port=port, log_level="warning")
    server = Server(config=config)
    serve_task = asyncio.create_task(server.serve())
    await done.wait()
    server.should_exit = True
    await serve_task

    code = result["code"]
    basic = base64.b64encode(
        f"{settings.x_client_id}:{settings.x_client_secret}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.x_redirect_uri,
                "client_id": settings.x_client_id,
                "code_verifier": verifier,
            },
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed: {resp.status_code} {resp.text}")

    payload = resp.json()
    refresh_token = payload.get("refresh_token", "")
    logger.info("\n=== Success ===")
    logger.info("Access token expires in: %s seconds", payload.get("expires_in"))
    logger.info("\nPaste this into your .env as X_REFRESH_TOKEN:\n")
    logger.info("    %s\n", refresh_token)


if __name__ == "__main__":
    asyncio.run(main())
