"""Redis fixed-window rate-limit with Postgres fallback.

Copy of CentralAuthService/app/security/rate_limit.py — single pattern across
all Signaris products. Redis is primary (fast, atomic, self-expiring); on
outage we fall to the `rate_limits` table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_asyncio
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("rate_limit")


class RateLimitExceeded(Exception):
    def __init__(self, key: str, limit: int, window_sec: int):
        self.key = key
        self.limit = limit
        self.window_sec = window_sec
        super().__init__(f"rate limit {limit}/{window_sec}s exceeded for {key}")


async def check_and_increment(
    redis: redis_asyncio.Redis,
    *,
    key: str,
    limit: int,
    window_sec: int,
    session: AsyncSession | None = None,
) -> int:
    full_key = f"rl:{key}"
    try:
        pipe = redis.pipeline()
        pipe.incr(full_key)
        pipe.expire(full_key, window_sec)
        count, _ = await pipe.execute()
    except Exception as e:  # noqa: BLE001 — redis outage, fall through
        log.warning("rate_limit.redis_unavailable", key=key, err=str(e))
        if session is not None:
            return await _db_check_and_increment(
                session, key=full_key, limit=limit, window_sec=window_sec
            )
        return 0  # fail-open

    if count > limit:
        raise RateLimitExceeded(key, limit, window_sec)
    return int(count)


async def _db_check_and_increment(
    session: AsyncSession,
    *,
    key: str,
    limit: int,
    window_sec: int,
) -> int:
    ws = window_start(window_sec)
    stmt = text(
        """
        INSERT INTO rate_limits (key, count, window_start)
        VALUES (:key, 1, :ws)
        ON CONFLICT (key) DO UPDATE SET
            count = CASE WHEN rate_limits.window_start < :ws
                         THEN 1
                         ELSE rate_limits.count + 1 END,
            window_start = CASE WHEN rate_limits.window_start < :ws
                                THEN :ws
                                ELSE rate_limits.window_start END
        RETURNING count
        """
    )
    result = await session.execute(stmt, {"key": key, "ws": ws})
    count = int(result.scalar_one())
    if count > limit:
        raise RateLimitExceeded(key, limit, window_sec)
    return count


def window_start(window_sec: int) -> datetime:
    now = datetime.now(UTC)
    floor = now - timedelta(seconds=now.timestamp() % window_sec)
    return floor.replace(microsecond=0)
