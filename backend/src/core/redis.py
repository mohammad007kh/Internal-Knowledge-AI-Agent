"""Redis async connection factory and cache helper utilities.

Module-level singleton pattern — initialised during lifespan startup,
consumed by middleware (direct import) and route-handlers (FastAPI dependency).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis

from src.core.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton — set in lifespan startup, used by middleware
redis_client: Redis | None = None


async def init_redis() -> None:
    """Initialise the Redis connection pool. Call once in lifespan startup."""
    global redis_client  # noqa: PLW0603
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=True,
        max_connections=20,
    )
    await redis_client.ping()
    logger.info("Redis connected: %s", settings.REDIS_URL)


async def close_redis() -> None:
    """Close the Redis connection pool. Call once in lifespan shutdown."""
    global redis_client  # noqa: PLW0603
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection closed.")


async def get_redis() -> Redis | None:
    """FastAPI dependency — returns the module-level Redis client."""
    return redis_client


async def redis_ping() -> bool:
    """Health-check helper. Returns ``True`` if Redis responds to PING."""
    if redis_client is None:
        return False
    try:
        return await redis_client.ping()
    except Exception:  # noqa: BLE001
        return False


# ─── Cache helpers ──────────────────────────────────────────────────────────────


async def cache_get(key: str) -> Any | None:
    """Return deserialised value or ``None`` if key is missing / Redis unavailable."""
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache_get failed for key=%s: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Serialise and store *value* with a TTL. No-op if Redis is unavailable."""
    if redis_client is None:
        return
    try:
        await redis_client.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache_set failed for key=%s: %s", key, exc)


async def cache_delete(key: str) -> None:
    """Delete a key. No-op if Redis is unavailable."""
    if redis_client is None:
        return
    try:
        await redis_client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache_delete failed for key=%s: %s", key, exc)
