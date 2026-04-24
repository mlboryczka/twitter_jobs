"""Async httpx-based X API client — retries, rate limits, cost logging.

All callers should use :class:`XClient.get` rather than talking to httpx
directly, so that every call lands in the ``api_calls`` ledger.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from sqlalchemy import insert

from twitter_jobs.db.models import ApiCall
from twitter_jobs.db.session import session_scope
from twitter_jobs.x_api.auth import XAuth
from twitter_jobs.x_api.pricing import estimate_cost

logger = logging.getLogger(__name__)

BASE_URL = "https://api.x.com"
DEFAULT_TIMEOUT = 30
MAX_5XX_RETRIES = 3
PROACTIVE_RL_THRESHOLD = 5


class XAPIError(Exception):
    """Raised when the X API returns a non-retryable error."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"X API error {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class XClient:
    """Async X API v2 client. Thin — individual endpoints live in endpoints.py."""

    def __init__(self, auth: XAuth, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._auth = auth
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "XClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        endpoint_key: str | None = None,
        resource_count_key: str | None = "data",
    ) -> dict[str, Any]:
        """GET ``path``, handling auth, retries, rate limits, and cost logging.

        Args:
            path: API path, e.g. ``/2/users/me``.
            params: Query parameters.
            endpoint_key: Key into pricing.PRICING for cost estimation.
            resource_count_key: JSON field whose length determines billed
                resource count. Defaults to ``data`` (a list). For singletons
                (users/me), pass ``None`` and we'll count 1.
        """
        attempt_5xx = 0
        while True:
            token = await self._auth.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            try:
                resp = await self._http.get(path, params=params, headers=headers)
            except httpx.RequestError as exc:
                logger.warning("httpx transport error on %s: %s", path, exc)
                attempt_5xx += 1
                if attempt_5xx > MAX_5XX_RETRIES:
                    raise
                await asyncio.sleep(2**attempt_5xx)
                continue

            # 429 — read reset header, sleep, retry once.
            if resp.status_code == 429:
                reset = resp.headers.get("x-rate-limit-reset")
                delay = _delay_until_reset(reset, default=60)
                logger.warning(
                    "X API 429 on %s; sleeping %.1fs until rate-limit reset",
                    path,
                    delay,
                )
                await asyncio.sleep(delay)
                # Single retry — re-enter loop exactly once for this case.
                token = await self._auth.get_access_token()
                headers = {"Authorization": f"Bearer {token}"}
                resp = await self._http.get(path, params=params, headers=headers)

            if 500 <= resp.status_code < 600:
                attempt_5xx += 1
                if attempt_5xx > MAX_5XX_RETRIES:
                    await self._log_api_call(path, resp.status_code, 0, 0, notes="5xx max retries")
                    raise XAPIError(resp.status_code, resp.text)
                backoff = 2**attempt_5xx
                logger.warning(
                    "X API %s on %s (attempt %d); backing off %ds",
                    resp.status_code,
                    path,
                    attempt_5xx,
                    backoff,
                )
                await asyncio.sleep(backoff)
                continue

            # At this point we've either got a 2xx or a 4xx we don't handle.
            if resp.status_code >= 400:
                await self._log_api_call(
                    path, resp.status_code, 0, 0, notes=resp.text[:500]
                )
                raise XAPIError(resp.status_code, resp.text)

            payload = resp.json()
            resource_count = _count_resources(payload, resource_count_key)
            cost = estimate_cost(endpoint_key or "", resource_count) if endpoint_key else 0.0
            await self._log_api_call(
                path, resp.status_code, cost, resource_count, endpoint_key=endpoint_key
            )

            # Proactive rate-limit throttle.
            remaining = _safe_int(resp.headers.get("x-rate-limit-remaining"))
            reset = resp.headers.get("x-rate-limit-reset")
            if remaining is not None and remaining < PROACTIVE_RL_THRESHOLD:
                delay = _delay_until_reset(reset, default=10)
                if delay > 0:
                    logger.info(
                        "Proactive throttle on %s: remaining=%s, sleeping %.1fs",
                        path,
                        remaining,
                        delay,
                    )
                    await asyncio.sleep(delay)

            return payload

    async def _log_api_call(
        self,
        path: str,
        status_code: int,
        cost_usd: float,
        tweets_returned: int,
        endpoint_key: str | None = None,
        notes: str | None = None,
    ) -> None:
        try:
            async with session_scope() as session:
                await session.execute(
                    insert(ApiCall).values(
                        endpoint=endpoint_key or path,
                        status_code=status_code,
                        cost_usd=cost_usd,
                        tweets_returned=tweets_returned,
                        notes=notes,
                    )
                )
        except Exception as exc:  # pragma: no cover — logging must not break the request
            logger.exception("failed to log api_call row: %s", exc)


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _delay_until_reset(reset_header: str | None, default: float) -> float:
    reset = _safe_int(reset_header)
    if reset is None:
        return default
    now = time.time()
    # x-rate-limit-reset is a unix timestamp (seconds).
    delay = max(reset - now, 0)
    # Add a small buffer so we don't race the reset.
    return delay + 1.0


def _count_resources(payload: dict[str, Any], key: str | None) -> int:
    if key is None:
        return 1
    data = payload.get(key)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return 1
    return 0
