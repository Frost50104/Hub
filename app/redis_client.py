"""Lazy singleton Redis client.

Hub didn't have a global Redis pool before 3.6.8 — the only consumer
(`app.security.rate_limit`) received Redis as an argument. With rate-limit
landing on multiple endpoints we need a single connection pool reused per
process. `redis.asyncio.from_url` already returns a pool-backed client, so
this module is just a thread-safe singleton + a `close()` for the lifespan.
"""

from __future__ import annotations

import redis.asyncio as redis_asyncio

from app.config import get_settings

_client: redis_asyncio.Redis | None = None


def get_redis() -> redis_asyncio.Redis:
    """Process-wide singleton — uvicorn workers each create their own."""
    global _client
    if _client is None:
        _client = redis_asyncio.from_url(
            get_settings().redis_url, decode_responses=False
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
