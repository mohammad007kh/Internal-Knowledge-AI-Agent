"""IP-based sliding-window rate limiter backed by Redis sorted sets."""

from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# (route_prefix, limit, window_seconds)
RATE_LIMIT_RULES: list[tuple[str, int, int]] = [
    ("/api/v1/auth/login", 10, 60),
    ("/api/v1/auth/refresh", 10, 60),
    ("/api/v1/", 100, 60),
]


def _get_client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For (first hop) if behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_rule(path: str) -> tuple[str, int, int] | None:
    """Return (prefix, limit, window_seconds) for the first matching rule, else None."""
    for prefix, limit, window in RATE_LIMIT_RULES:
        if path.startswith(prefix):
            return prefix, limit, window
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter using Redis sorted sets.

    Falls back to allow-all when Redis is unavailable.
    """

    def __init__(self, app: ASGIApp, redis_client=None) -> None:  # noqa: ANN001
        super().__init__(app)
        self._redis = redis_client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rule = _match_rule(request.url.path)
        if rule is None:
            return await call_next(request)

        prefix, limit, window = rule
        ip = _get_client_ip(request)
        key = f"rate:{prefix}:{ip}"
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
                    return JSONResponse(
                        status_code=429,
                        content={
                            "type": "about:blank",
                            "title": "Too Many Requests",
                            "status": 429,
                            "detail": f"Rate limit exceeded. Try again in {window} seconds.",
                        },
                        media_type="application/problem+json",
                        headers={
                            "Retry-After": str(window),
                            "X-RateLimit-Limit": str(limit),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(reset_at),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Rate limiter Redis error — allowing request: %s", exc)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response
