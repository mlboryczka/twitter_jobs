"""Smoke test — calls users/me, prints username, confirms an api_calls row landed."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from twitter_jobs.db.models import ApiCall  # noqa: E402
from twitter_jobs.db.session import session_scope  # noqa: E402
from twitter_jobs.x_api.auth import XAuth  # noqa: E402
from twitter_jobs.x_api.client import XClient  # noqa: E402
from twitter_jobs.x_api.endpoints import get_me  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("smoke_test")


async def main() -> int:
    auth = XAuth()
    async with XClient(auth) as client:
        payload = await get_me(client)
        user = payload.get("data", {})
        logger.info(
            "Authenticated as @%s (%s, id=%s)",
            user.get("username"),
            user.get("name"),
            user.get("id"),
        )

    async with session_scope() as session:
        result = await session.execute(
            select(ApiCall).order_by(ApiCall.id.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
    if row is None:
        logger.error("No api_calls row was written — something is wrong with logging.")
        return 1
    logger.info(
        "Latest api_calls row: id=%s endpoint=%s status=%s cost_usd=%s",
        row.id,
        row.endpoint,
        row.status_code,
        row.cost_usd,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
