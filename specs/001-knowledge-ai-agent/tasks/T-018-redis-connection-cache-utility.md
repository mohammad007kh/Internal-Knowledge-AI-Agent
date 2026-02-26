# T-018 — Redis Connection Factory + Cache Utility

---
id: T-018
title: Redis Async Connection Factory and Cache Helper Utilities
status: Not Started
created: 2026-02-26
phase: Phase 0 — Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-004]
blocks: [T-016, T-019, T-025]
estimated_effort: 1.5h
---

## Goal

Create a managed Redis connection using `redis.asyncio` (part of the `redis` package) with a module-level singleton for use by middleware and a FastAPI dependency for use by route handlers. Also provide `cache_get`, `cache_set`, and `cache_delete` helpers that encapsulate serialization and TTL management.

---

## Acceptance Criteria

- [ ] `redis_client` module-level singleton is available at `src.core.redis` after `lifespan` startup
- [ ] Connection string read from `settings.REDIS_URL` (e.g. `redis://redis:6379/0`)
- [ ] `get_redis()` FastAPI dependency yields the module-level client (does not open a new connection per request)
- [ ] `cache_get(key: str) -> Any | None` returns deserialized Python value or `None`
- [ ] `cache_set(key: str, value: Any, ttl: int = 300)` serializes and sets with TTL
- [ ] `cache_delete(key: str)` removes a key
- [ ] All cache helpers handle `redis.exceptions.RedisError` gracefully — log warning, return `None` / no-op
- [ ] Connection health check is part of `GET /health` response (ping → `{"redis": "ok" | "degraded"}`)
- [ ] Unit tests: cache round-trip, missing key returns None, error returns None without raising
- [ ] Integration test: Redis container in CI (already in `docker-compose.yml`, T-007 pytest services)

---

## Files to Create / Update

| Path | Action |
|------|---------|
| `backend/src/core/redis.py` | Create — singleton + dependency + cache helpers |
| `backend/src/main.py` | Update — initialize redis in lifespan |
| `backend/src/api/health.py` | Update — include Redis ping in health response |
| `backend/tests/unit/test_redis_cache.py` | Create |

---

## Implementation

### `backend/src/core/redis.py`

```python
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
    """Initialize the Redis connection pool. Call once in lifespan startup."""
    global redis_client
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
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection closed.")


async def get_redis() -> Redis | None:
    """FastAPI dependency — yields the module-level Redis client."""
    return redis_client


async def redis_ping() -> bool:
    """Health check helper. Returns True if Redis responds."""
    if redis_client is None:
        return False
    try:
        return await redis_client.ping()
    except Exception:  # noqa: BLE001
        return False


# ─── Cache helpers ──────────────────────────────────────────────────────────────

async def cache_get(key: str) -> Any | None:
    """Return deserialized value or None if key is missing / Redis is unavailable."""
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
    """Serialize and store value with a TTL. No-op if Redis is unavailable."""
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
```

### Update `backend/src/main.py` lifespan

```python
from src.core.redis import init_redis, close_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await run_migrations()        # from T-014
    await init_redis()            # ← add this
    await bootstrap_admin()       # from T-020
    yield
    # Shutdown
    await close_redis()           # ← add this
    await engine.dispose()
```

### Update `backend/src/api/health.py`

```python
from fastapi import APIRouter
from src.core.redis import redis_ping

router = APIRouter()

@router.get("/health")
async def health():
    redis_ok = await redis_ping()
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": "ok" if redis_ok else "degraded",
    }
```

---

## Tests

### `backend/tests/unit/test_redis_cache.py`

```python
import pytest
from unittest.mock import AsyncMock, patch
import src.core.redis as redis_module


@pytest.mark.asyncio
async def test_cache_set_and_get(mock_redis):
    """Round-trip: set then get returns same value."""
    with patch.object(redis_module, "redis_client", mock_redis):
        mock_redis.setex = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"count": 42}')
        await redis_module.cache_set("test:key", {"count": 42}, ttl=60)
        result = await redis_module.cache_get("test:key")
        assert result == {"count": 42}


@pytest.mark.asyncio
async def test_cache_get_missing_key(mock_redis):
    with patch.object(redis_module, "redis_client", mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        result = await redis_module.cache_get("nonexistent:key")
        assert result is None


@pytest.mark.asyncio
async def test_cache_get_redis_error(mock_redis):
    """Redis error should return None, not raise."""
    with patch.object(redis_module, "redis_client", mock_redis):
        mock_redis.get = AsyncMock(side_effect=Exception("Connection refused"))
        result = await redis_module.cache_get("any:key")
        assert result is None


@pytest.mark.asyncio
async def test_cache_get_no_client():
    with patch.object(redis_module, "redis_client", None):
        result = await redis_module.cache_get("any:key")
        assert result is None
```

---

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Security | Rate-limit IP (uses Redis) |

### Domain Rules
- The Redis singleton must be initialized in the `lifespan` startup — NOT imported at module load time
- Redis errors must NEVER crash the application — all cache helpers must fail silently
- `REDIS_URL` comes from `settings`, never from `os.environ` directly
- The cache helpers are for volatile data (rate limits, short-lived tokens, embeddings cache). Do NOT use them to store user data or anything requiring ACID guarantees.
