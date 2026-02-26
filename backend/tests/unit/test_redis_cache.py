"""Unit tests for src.core.redis — connection, cache helpers, health check."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.core.redis as redis_module
from src.core.redis import (
    cache_delete,
    cache_get,
    cache_set,
    close_redis,
    get_redis,
    init_redis,
    redis_ping,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return a mock Redis client with common methods stubbed."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    mock.aclose = AsyncMock()
    return mock


# ── cache_get ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_get_returns_deserialized_value(mock_redis: AsyncMock) -> None:
    """Round-trip: stored JSON is deserialised on read."""
    mock_redis.get = AsyncMock(return_value=json.dumps({"count": 42}))
    with patch.object(redis_module, "redis_client", mock_redis):
        result = await cache_get("test:key")
    assert result == {"count": 42}


@pytest.mark.asyncio
async def test_cache_get_missing_key_returns_none(mock_redis: AsyncMock) -> None:
    mock_redis.get = AsyncMock(return_value=None)
    with patch.object(redis_module, "redis_client", mock_redis):
        result = await cache_get("nonexistent:key")
    assert result is None


@pytest.mark.asyncio
async def test_cache_get_redis_error_returns_none(mock_redis: AsyncMock) -> None:
    """Redis error must return None — never raise."""
    mock_redis.get = AsyncMock(side_effect=Exception("Connection refused"))
    with patch.object(redis_module, "redis_client", mock_redis):
        result = await cache_get("any:key")
    assert result is None


@pytest.mark.asyncio
async def test_cache_get_no_client_returns_none() -> None:
    with patch.object(redis_module, "redis_client", None):
        result = await cache_get("any:key")
    assert result is None


# ── cache_set ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_set_calls_setex(mock_redis: AsyncMock) -> None:
    with patch.object(redis_module, "redis_client", mock_redis):
        await cache_set("test:key", {"count": 42}, ttl=60)
    mock_redis.setex.assert_awaited_once_with("test:key", 60, json.dumps({"count": 42}))


@pytest.mark.asyncio
async def test_cache_set_redis_error_is_noop(mock_redis: AsyncMock) -> None:
    mock_redis.setex = AsyncMock(side_effect=Exception("Connection refused"))
    with patch.object(redis_module, "redis_client", mock_redis):
        await cache_set("test:key", "value")  # must not raise


@pytest.mark.asyncio
async def test_cache_set_no_client_is_noop() -> None:
    with patch.object(redis_module, "redis_client", None):
        await cache_set("test:key", "value")  # must not raise


# ── cache_delete ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_delete_calls_delete(mock_redis: AsyncMock) -> None:
    with patch.object(redis_module, "redis_client", mock_redis):
        await cache_delete("test:key")
    mock_redis.delete.assert_awaited_once_with("test:key")


@pytest.mark.asyncio
async def test_cache_delete_redis_error_is_noop(mock_redis: AsyncMock) -> None:
    mock_redis.delete = AsyncMock(side_effect=Exception("Connection refused"))
    with patch.object(redis_module, "redis_client", mock_redis):
        await cache_delete("test:key")  # must not raise


@pytest.mark.asyncio
async def test_cache_delete_no_client_is_noop() -> None:
    with patch.object(redis_module, "redis_client", None):
        await cache_delete("test:key")  # must not raise


# ── redis_ping ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_ping_returns_true(mock_redis: AsyncMock) -> None:
    mock_redis.ping = AsyncMock(return_value=True)
    with patch.object(redis_module, "redis_client", mock_redis):
        assert await redis_ping() is True


@pytest.mark.asyncio
async def test_redis_ping_returns_false_on_error(mock_redis: AsyncMock) -> None:
    mock_redis.ping = AsyncMock(side_effect=Exception("timeout"))
    with patch.object(redis_module, "redis_client", mock_redis):
        assert await redis_ping() is False


@pytest.mark.asyncio
async def test_redis_ping_returns_false_no_client() -> None:
    with patch.object(redis_module, "redis_client", None):
        assert await redis_ping() is False


# ── get_redis ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_redis_returns_client(mock_redis: AsyncMock) -> None:
    with patch.object(redis_module, "redis_client", mock_redis):
        result = await get_redis()
    assert result is mock_redis


@pytest.mark.asyncio
async def test_get_redis_returns_none_when_not_initialised() -> None:
    with patch.object(redis_module, "redis_client", None):
        result = await get_redis()
    assert result is None


# ── init_redis / close_redis ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_redis_sets_client() -> None:
    mock_conn = AsyncMock()
    mock_conn.ping = AsyncMock(return_value=True)
    with (
        patch("src.core.redis.aioredis") as mock_aioredis,
        patch.object(redis_module, "redis_client", None),
    ):
        mock_aioredis.from_url.return_value = mock_conn
        await init_redis()
        mock_conn.ping.assert_awaited_once()
        assert redis_module.redis_client is mock_conn


@pytest.mark.asyncio
async def test_close_redis_clears_client(mock_redis: AsyncMock) -> None:
    with patch.object(redis_module, "redis_client", mock_redis):
        await close_redis()
    mock_redis.aclose.assert_awaited_once()
    assert redis_module.redis_client is None
