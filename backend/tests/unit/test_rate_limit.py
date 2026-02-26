"""Unit tests for IP-based rate limiting middleware."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.middleware.rate_limit import (
    RateLimitMiddleware,
    _get_client_ip,
    _match_rule,
    RATE_LIMIT_RULES,
)

import src.core.redis as redis_module


# ── Helper-function tests ──────────────────────────────────────


class TestGetClientIP:
    """Tests for _get_client_ip helper."""

    def test_uses_x_forwarded_for_when_present(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        assert _get_client_ip(request) == "1.2.3.4"

    def test_uses_client_host_as_fallback(self):
        request = MagicMock()
        request.headers = {}
        request.client.host = "10.0.0.1"
        assert _get_client_ip(request) == "10.0.0.1"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert _get_client_ip(request) == "unknown"


class TestMatchRule:
    """Tests for _match_rule helper."""

    def test_auth_login_matches_strict_rule(self):
        result = _match_rule("/api/v1/auth/login")
        assert result == ("/api/v1/auth/login", 10, 60)

    def test_auth_refresh_matches_strict_rule(self):
        result = _match_rule("/api/v1/auth/refresh")
        assert result == ("/api/v1/auth/refresh", 10, 60)

    def test_general_api_matches_broad_rule(self):
        result = _match_rule("/api/v1/users")
        assert result == ("/api/v1/", 100, 60)

    def test_health_endpoint_no_match(self):
        result = _match_rule("/health")
        assert result is None

    def test_docs_endpoint_no_match(self):
        result = _match_rule("/docs")
        assert result is None

    def test_auth_login_matches_before_general(self):
        """Auth rules appear first in RATE_LIMIT_RULES so they take priority."""
        # Verify rule ordering
        auth_login_idx = next(
            i for i, (p, _, _) in enumerate(RATE_LIMIT_RULES) if "auth/login" in p
        )
        general_idx = next(
            i
            for i, (p, _, _) in enumerate(RATE_LIMIT_RULES)
            if p == "/api/v1/"
        )
        assert auth_login_idx < general_idx


# ── Middleware integration tests (no real Redis) ──────────────


@pytest.fixture()
def _mock_redis_pipeline():
    """Return a mock Redis client whose pipeline returns controlled results."""

    def _factory(count: int):
        pipe = AsyncMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        pipe.execute = AsyncMock(return_value=[None, None, count, None])

        redis = MagicMock()
        redis.pipeline = MagicMock(return_value=pipe)
        return redis

    return _factory


@pytest.fixture()
def _app_with_redis(_mock_redis_pipeline):
    """Build a minimal FastAPI app with RateLimitMiddleware + mock Redis."""
    from fastapi import FastAPI

    original = redis_module.redis_client

    def _factory(count: int):
        mock_redis = _mock_redis_pipeline(count)
        redis_module.redis_client = mock_redis

        inner_app = FastAPI()

        @inner_app.get("/api/v1/ping")
        async def ping():
            return {"ping": "pong"}

        @inner_app.post("/api/v1/auth/login")
        async def login():
            return {"token": "fake"}

        inner_app.add_middleware(RateLimitMiddleware)
        return inner_app

    yield _factory
    redis_module.redis_client = original


@pytest.mark.asyncio
async def test_under_limit_passes(_app_with_redis):
    """Request within limit should succeed and include rate-limit headers."""
    from httpx import ASGITransport, AsyncClient

    test_app = _app_with_redis(count=1)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/ping")

    assert resp.status_code == 200
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers
    assert resp.headers["X-RateLimit-Limit"] == "100"


@pytest.mark.asyncio
async def test_at_limit_passes(_app_with_redis):
    """Request exactly at the limit should still succeed."""
    from httpx import ASGITransport, AsyncClient

    test_app = _app_with_redis(count=100)  # exactly at limit
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/ping")

    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_over_limit_returns_429(_app_with_redis):
    """Request over limit should return 429 with RFC 7807 body."""
    from httpx import ASGITransport, AsyncClient

    test_app = _app_with_redis(count=101)  # over limit
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/ping")

    assert resp.status_code == 429
    assert resp.headers["content-type"] == "application/problem+json"
    assert "Retry-After" in resp.headers
    assert resp.headers["X-RateLimit-Remaining"] == "0"

    body = resp.json()
    assert body["status"] == 429
    assert body["title"] == "Too Many Requests"
    assert "type" in body
    assert "detail" in body


@pytest.mark.asyncio
async def test_auth_route_stricter_limit(_app_with_redis):
    """Auth login at count=11 should be rejected (limit=10)."""
    from httpx import ASGITransport, AsyncClient

    test_app = _app_with_redis(count=11)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/auth/login")

    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Limit"] == "10"


@pytest.mark.asyncio
async def test_no_redis_allows_request():
    """When redis_client is None, requests pass through."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    test_app = FastAPI()

    @test_app.get("/api/v1/ping")
    async def ping():
        return {"ping": "pong"}

    test_app.add_middleware(RateLimitMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/ping")

    assert resp.status_code == 200
    # Headers still present with defaults
    assert "X-RateLimit-Limit" in resp.headers


@pytest.mark.asyncio
async def test_redis_error_allows_request():
    """When Redis raises an exception, request is allowed with a warning."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))

    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)

    test_app = FastAPI()

    @test_app.get("/api/v1/ping")
    async def ping():
        return {"ping": "pong"}

    test_app.add_middleware(RateLimitMiddleware)

    with patch.object(redis_module, "redis_client", redis):
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/ping")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_non_api_route_not_limited():
    """Routes outside /api/v1/ should not be rate limited."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    test_app.add_middleware(RateLimitMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert "X-RateLimit-Limit" not in resp.headers


# ── Integration test (sequential requests with stateful Redis mock) ──────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_login_11th_request_returns_429():
    """11 rapid POST requests to /api/v1/auth/login — 11th returns 429.

    Uses a stateful Redis mock that accumulates ZADD entries across
    calls so the sliding-window counter increments realistically.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    # Stateful mock: tracks sorted-set members so zcard grows per request
    members: dict[str, dict] = {}  # key -> {member: score}

    class _FakePipeline:
        def __init__(self) -> None:
            self._ops: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def zremrangebyscore(self, key: str, _min, _max):
            # Remove expired members
            if key in members:
                members[key] = {
                    m: s for m, s in members[key].items() if s > _max
                }
            self._ops.append(None)

        def zadd(self, key: str, mapping: dict):
            members.setdefault(key, {}).update(mapping)
            self._ops.append(None)

        def zcard(self, key: str):
            self._ops.append(("zcard", key))

        def expire(self, key: str, ttl: int):
            self._ops.append(None)

        async def execute(self):
            results = []
            for op in self._ops:
                if isinstance(op, tuple) and op[0] == "zcard":
                    results.append(len(members.get(op[1], {})))
                else:
                    results.append(None)
            self._ops.clear()
            return results

    class _FakeRedis:
        def pipeline(self, **_kwargs):
            return _FakePipeline()

    test_app = FastAPI()

    @test_app.post("/api/v1/auth/login")
    async def login():
        return {"token": "fake"}

    test_app.add_middleware(RateLimitMiddleware)

    with patch.object(redis_module, "redis_client", _FakeRedis()):
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            statuses: list[int] = []
            for _ in range(11):
                resp = await client.post("/api/v1/auth/login")
                statuses.append(resp.status_code)

    # First 10 should succeed, 11th should be 429
    assert statuses[:10] == [200] * 10, f"Expected 10 successes, got {statuses[:10]}"
    assert statuses[10] == 429, f"Expected 429 on 11th request, got {statuses[10]}"
