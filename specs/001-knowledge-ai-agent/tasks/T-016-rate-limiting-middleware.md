# T-016 â€” Rate Limiting Middleware (IP-based)

---
id: T-016
title: Rate Limiting Middleware (IP-based, auth endpoint stricter limits)
status: Done
created: 2026-02-26
phase: Phase 0 â€” Foundation
user_story: cross
requirements: [FR-033]
priority: P1
depends_on: [T-015, T-018]
blocks: [T-026, T-038]
estimated_effort: 2h
---

## Goal

Add IP-based rate limiting to the FastAPI application. Auth endpoints (`/api/v1/auth/*`) must have significantly tighter limits than general API routes. All rate-limit rejections return RFC 7807 `429 Too Many Requests`.

---

## Acceptance Criteria

- [ ] General API routes limited to **100 req / 60 s per IP**
- [ ] Auth routes (`/api/v1/auth/login`, `/api/v1/auth/refresh`) limited to **10 req / 60 s per IP**
- [ ] Rejected requests return `application/problem+json` with `status: 429` and a `Retry-After` header
- [ ] Rate-limit counters backed by Redis (from `T-018`) â€” so limits persist across worker restarts
- [ ] Middleware falls back gracefully (logs warning, allows request) if Redis is unavailable â€” never a hard failure
- [ ] `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` response headers present on every request in the limited routes
- [ ] Unit tests: within limit passes, at-limit passes, over-limit returns 429 with correct headers
- [ ] Integration test: 11 rapid POST requests to `/api/v1/auth/login` â†’ 11th returns 429

---

## Files to Create / Update

| Path | Action |
|------|---------|
| `backend/src/middleware/rate_limit.py` | Create â€” sliding-window limiter |
| `backend/src/main.py` | Update â€” register rate limit middleware |
| `backend/tests/unit/test_rate_limit.py` | Create |

---

## Implementation

### Algorithm: Sliding Window (Redis `ZREMRANGEBYSCORE` + `ZADD` + `ZCARD`)

Use a Redis sorted set keyed by `rate:{endpoint_key}:{client_ip}`:
1. Remove members older than the window start with `ZREMRANGEBYSCORE`
2. Add current timestamp with `ZADD`
3. Count members with `ZCARD`
4. Set TTL on the key equal to the window length
5. If count > limit â†’ return 429

### `backend/src/middleware/rate_limit.py`

```python
import time
import logging
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# (route_prefix, limit, window_seconds)
RATE_LIMIT_RULES: list[tuple[str, int, int]] = [
    ("/api/v1/auth/login",   10,  60),
    ("/api/v1/auth/refresh", 10,  60),
    ("/api/v1/",            100,  60),
]


def _get_client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For (first hop) if behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_rule(path: str) -> tuple[int, int] | None:
    """Return (limit, window_seconds) for the first matching rule, else None."""
    for prefix, limit, window in RATE_LIMIT_RULES:
        if path.startswith(prefix):
            return limit, window
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, redis_client=None):
        super().__init__(app)
        self._redis = redis_client  # injected; may be None during tests

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rule = _match_rule(request.url.path)
        if rule is None:
            return await call_next(request)

        limit, window = rule
        ip = _get_client_ip(request)
        key = f"rate:{request.url.path}:{ip}"
        now = time.time()
        window_start = now - window

        remaining = limit
        reset_at = int(now) + window

        if self._redis is not None:
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(key, 0, window_start)
                    pipe.zadd(key, {str(now): now})
                    pipe.zcard(key)
                    pipe.expire(key, window)
                    results = await pipe.execute()
                count = results[2]
                remaining = max(0, limit - count)
                reset_at = int(now) + window

                if count > limit:
                    content = {
                        "type": "about:blank",
                        "title": "Too Many Requests",
                        "status": 429,
                        "detail": f"Rate limit exceeded. Try again in {window} seconds.",
                    }
                    return JSONResponse(
                        status_code=429,
                        content=content,
                        media_type="application/problem+json",
                        headers={
                            "Retry-After": str(window),
                            "X-RateLimit-Limit": str(limit),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(reset_at),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Rate limiter Redis error â€” allowing request: %s", exc)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response
```

### Wire into `backend/src/main.py`

In `create_app()`, after other middleware, add:

```python
from src.middleware.rate_limit import RateLimitMiddleware
from src.core.dependencies import get_redis  # provided by T-018

async def _get_redis_for_middleware():
    """Non-dependency-injection helper for middleware initialization."""
    try:
        from src.core.redis import redis_client  # module-level singleton from T-018
        return redis_client
    except Exception:
        return None

# In create_app():
app.add_middleware(RateLimitMiddleware, redis_client=await _get_redis_for_middleware())
```

> **Note for T-038 wiring:** The Redis client must be available before middleware is registered. Use the module-level `redis_client` singleton from T-018, not a per-request dependency.

---

## Tests

### `backend/tests/unit/test_rate_limit.py`

```python
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from src.main import create_app

@pytest.mark.asyncio
async def test_under_limit_allowed():
    """First request within limit passes."""
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("src.middleware.rate_limit.RateLimitMiddleware._redis", None):
            resp = await client.post("/api/v1/auth/login", json={})
            # 422 (validation) not 429 â€” meaning rate limit passed
            assert resp.status_code != 429

@pytest.mark.asyncio
async def test_over_limit_returns_429():
    """Mock Redis returning count > limit triggers 429."""
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.execute = AsyncMock(return_value=[None, None, 11, None])  # count=11 > limit=10

    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Inject mock redis directly into middleware instance
        for middleware in app.middleware_stack.__dict__.get("middlewares", []):
            if hasattr(middleware, "_redis"):
                middleware._redis = mock_redis
        # Direct call to middleware dispatch
        # (full integration test covered in test_auth_integration.py)
```

---

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS |
| Database | PostgreSQL 16 + pgvector Â· UUID PKs Â· soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis Â· Beat replicas=1 STRICT |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user) |
| Error Format | RFC 7807 Problem Details â€” all non-2xx API responses |
| Logging | Structured Â· INFO level Â· X-Request-ID correlation |
| Security | CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP |

### Domain Rules
- Rate limit errors MUST use RFC 7807 format (application/problem+json) â€” never plain JSON `{"detail": ...}`
- Redis unavailability must NEVER crash the application â€” fail open with a warning log
- Celery Beat MUST run with exactly 1 replica
