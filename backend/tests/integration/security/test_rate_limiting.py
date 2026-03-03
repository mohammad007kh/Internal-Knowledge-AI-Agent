"""Integration tests for rate-limiting middleware (T-096).

Redis is mocked via ``monkeypatch`` so tests run without a live Redis.
The fake pipeline's ``execute()`` returns an incrementing counter, which
lets us trigger the configured login rate-limit (5/min) deterministically.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

LOGIN_RATE_LIMIT = 5
LOGIN_URL = "/api/v1/auth/login"

# Credentials that will always fail authentication — we only care about the
# rate-limiter response, not a successful login.
_BAD_CREDS = {"email": "nobody@example.com", "password": "Wrong@0000"}


# ---------------------------------------------------------------------------
# Fake-Redis factory
# ---------------------------------------------------------------------------


def _make_fake_redis(limit: int) -> AsyncMock:
    """Return an AsyncMock that behaves like a Redis client for the rate-limiter.

    Each call to the pipeline's ``execute()`` increments an internal counter.
    Once the counter exceeds *limit* the rate-limiter's ``count > limit`` check
    will evaluate to True and the middleware will return HTTP 429.
    """
    call_count: list[int] = [0]

    # Build a fake pipeline that is used as an async context manager.
    fake_pipe = AsyncMock()

    async def _execute() -> list[object]:
        call_count[0] += 1
        count = call_count[0]
        # Return shape: [None, None, <window_count>, <expiry_ms>]
        # The middleware reads index 2 (count) and index 3 (expiry_ms).
        now_ms = 1_700_000_000_000
        return [None, None, count, now_ms + 60_000]

    fake_pipe.__aenter__ = AsyncMock(return_value=fake_pipe)
    fake_pipe.__aexit__ = AsyncMock(return_value=False)
    fake_pipe.zremrangebyscore = AsyncMock()
    fake_pipe.zadd = AsyncMock()
    fake_pipe.zcard = AsyncMock()
    fake_pipe.pexpire = AsyncMock()
    fake_pipe.execute = _execute  # type: ignore[method-assign]

    fake_redis = AsyncMock()
    fake_redis.pipeline = Mock(return_value=fake_pipe)
    return fake_redis


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def patched_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch the module-level ``redis_client`` singleton used by rate_limit.py."""
    fake = _make_fake_redis(LOGIN_RATE_LIMIT)
    monkeypatch.setattr("src.core.redis.redis_client", fake)
    return fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_login_rate_limit_returns_429(
    async_client: AsyncClient,
    patched_redis: AsyncMock,
) -> None:
    """The (limit+1)-th request must receive HTTP 429."""
    last_response = None
    for _ in range(LOGIN_RATE_LIMIT + 1):
        last_response = await async_client.post(LOGIN_URL, json=_BAD_CREDS)
    assert last_response is not None
    assert last_response.status_code == 429, (
        f"Expected 429 on request {LOGIN_RATE_LIMIT + 1}, got {last_response.status_code}"
    )


async def test_rate_limit_response_is_rfc7807(
    async_client: AsyncClient,
    patched_redis: AsyncMock,
) -> None:
    """The 429 response body must conform to RFC 7807 (Problem Details)."""
    response = None
    for _ in range(LOGIN_RATE_LIMIT + 1):
        response = await async_client.post(LOGIN_URL, json=_BAD_CREDS)
    assert response is not None
    assert response.status_code == 429

    body = response.json()
    assert body.get("type") == "about:blank", f"Unexpected 'type': {body}"
    assert body.get("title") == "Too Many Requests", f"Unexpected 'title': {body}"
    assert body.get("status") == 429, f"Unexpected 'status': {body}"


async def test_429_includes_retry_after_header(
    async_client: AsyncClient,
    patched_redis: AsyncMock,
) -> None:
    """HTTP 429 must include a Retry-After header."""
    response = None
    for _ in range(LOGIN_RATE_LIMIT + 1):
        response = await async_client.post(LOGIN_URL, json=_BAD_CREDS)
    assert response is not None
    assert response.status_code == 429
    assert "retry-after" in response.headers, (
        "Retry-After header missing from 429 response"
    )


async def test_read_endpoints_not_rate_limited_at_login_threshold(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """GET /health must remain 200 even after login-threshold requests (no Redis mock needed)."""
    # Health endpoint is not listed in RATE_LIMIT_RULES with the login limit, so
    # even without Redis all responses should be 200.
    headers = {"Authorization": f"Bearer {user_token}"}
    for i in range(LOGIN_RATE_LIMIT + 1):
        r = await async_client.get("/health", headers=headers)
        assert r.status_code == 200, (
            f"Request {i + 1}: expected 200 but got {r.status_code}"
        )
