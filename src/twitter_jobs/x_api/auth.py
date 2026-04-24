"""OAuth 2.0 PKCE token management for the X API.

X rotates refresh tokens on every use. We persist the newest refresh token to
``secrets/x_refresh_token`` (file-based, survives restarts) and also update the
in-memory copy. The .env file is treated as the *initial* source — after the
first successful refresh, the persisted file takes precedence.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from twitter_jobs.config import Settings, get_settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.x.com/2/oauth2/token"
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
SCOPES = "tweet.read users.read bookmark.read offline.access"
# Refresh a little early so in-flight requests don't fail at the token boundary.
REFRESH_MARGIN_SECONDS = 5 * 60


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: float  # unix seconds


class XAuth:
    """Holds the current access token and manages refresh-token rotation."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = asyncio.Lock()
        self._token: TokenBundle | None = None
        self._persisted_path: Path = self._settings.refresh_token_file

    def _load_initial_refresh_token(self) -> str:
        """Prefer the persisted file (rotated) over .env (initial)."""
        if self._persisted_path.exists():
            value = self._persisted_path.read_text().strip()
            if value:
                return value
        return self._settings.x_refresh_token

    def _persist_refresh_token(self, refresh_token: str) -> None:
        self._persisted_path.parent.mkdir(parents=True, exist_ok=True)
        self._persisted_path.write_text(refresh_token + "\n")
        try:
            self._persisted_path.chmod(0o600)
        except OSError:
            pass

    async def get_access_token(self) -> str:
        """Return a usable access token, refreshing if near expiry."""
        async with self._lock:
            now = time.time()
            if self._token and self._token.expires_at - now > REFRESH_MARGIN_SECONDS:
                return self._token.access_token
            await self._refresh()
            assert self._token is not None
            return self._token.access_token

    async def _refresh(self) -> None:
        refresh_token = (
            self._token.refresh_token if self._token else self._load_initial_refresh_token()
        )
        if not refresh_token:
            raise RuntimeError(
                "No X refresh token available. Run scripts/run_oauth_flow.py "
                "and put the refresh token in .env."
            )

        basic = base64.b64encode(
            f"{self._settings.x_client_id}:{self._settings.x_client_secret}".encode()
        ).decode()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._settings.x_client_id,
        }
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            logger.error(
                "X OAuth refresh failed: %s %s", resp.status_code, resp.text
            )
            resp.raise_for_status()

        payload = resp.json()
        access_token = payload["access_token"]
        new_refresh_token = payload.get("refresh_token", refresh_token)
        expires_in = int(payload.get("expires_in", 7200))
        self._token = TokenBundle(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_at=time.time() + expires_in,
        )
        if new_refresh_token != refresh_token:
            self._persist_refresh_token(new_refresh_token)
            logger.info("Rotated X refresh token persisted to %s", self._persisted_path)
        else:
            logger.debug("X refresh token unchanged by rotation")
