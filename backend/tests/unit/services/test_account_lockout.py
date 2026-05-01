"""Unit tests for AccountLockout (Slice D — per-email-hash account lockout)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import AccountLockedError, RedisUnavailableError
from src.services.account_lockout import AccountLockout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    enabled: bool = True,
    require_redis: bool = True,
    max_fails: int = 10,
    window: int = 900,
    duration: int = 1800,
) -> SimpleNamespace:
    """Lightweight stand-in for the real Settings object."""
    return SimpleNamespace(
        LOCKOUT_ENABLED=enabled,
        LOCKOUT_REQUIRE_REDIS=require_redis,
        LOCKOUT_MAX_FAILS=max_fails,
        LOCKOUT_WINDOW_SECS=window,
        LOCKOUT_DURATION_SECS=duration,
    )


def _make_redis(
    *,
    ttl_value: int = -2,
    pipeline_results: list[object] | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics the async redis client surface used."""
    redis = MagicMock()

    redis.ttl = AsyncMock(return_value=ttl_value)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=2)

    pipe = MagicMock()
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zcard = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=pipeline_results or [0, 1, 1, 1])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmailHash:
    def test_email_hash_is_lowercase_trimmed(self) -> None:
        """Hash must be case-insensitive and whitespace-tolerant."""
        a = AccountLockout._hash("  Alice@Example.COM  ")
        b = AccountLockout._hash("alice@example.com")
        assert a == b

    def test_email_hash_distinguishes_different_emails(self) -> None:
        a = AccountLockout._hash("alice@example.com")
        b = AccountLockout._hash("bob@example.com")
        assert a != b


class TestCheck:
    @pytest.mark.asyncio
    async def test_check_passes_when_no_failures(self) -> None:
        """No locked-key in Redis → check is a no-op."""
        redis = _make_redis(ttl_value=-2)  # key does not exist
        svc = AccountLockout(redis_client=redis, settings=_make_settings())

        # Should NOT raise
        await svc.check("alice@example.com")
        redis.ttl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_raises_when_locked(self) -> None:
        """Locked-key TTL > 0 → AccountLockedError with retry_after_seconds."""
        redis = _make_redis(ttl_value=600)
        svc = AccountLockout(redis_client=redis, settings=_make_settings())

        with pytest.raises(AccountLockedError) as ei:
            await svc.check("alice@example.com")

        assert ei.value.extra.get("retry_after_seconds") == 600
        assert ei.value.status_code == 423

    @pytest.mark.asyncio
    async def test_check_disabled_is_noop(self) -> None:
        redis = _make_redis(ttl_value=600)  # locked, but enabled=False
        svc = AccountLockout(
            redis_client=redis,
            settings=_make_settings(enabled=False),
        )
        await svc.check("alice@example.com")  # should NOT raise
        redis.ttl.assert_not_awaited()


class TestRecordFailure:
    @pytest.mark.asyncio
    async def test_record_failure_increments_counter(self) -> None:
        """A single failed attempt below threshold does NOT lock."""
        redis = _make_redis(pipeline_results=[0, 1, 3, 1])
        svc = AccountLockout(redis_client=redis, settings=_make_settings(max_fails=10))

        await svc.record_failure("alice@example.com")

        # Pipeline executed
        redis.pipeline.assert_called_once_with(transaction=True)
        # Lock-key NOT written
        redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_failure_sets_lock_at_threshold(self) -> None:
        """When count >= max_fails, the locked-key is set with TTL."""
        redis = _make_redis(pipeline_results=[0, 1, 10, 1])
        svc = AccountLockout(
            redis_client=redis,
            settings=_make_settings(max_fails=10, duration=1800),
        )

        await svc.record_failure("alice@example.com")

        redis.set.assert_awaited_once()
        kwargs = redis.set.await_args.kwargs
        args = redis.set.await_args.args
        # Locked-key first arg, "1" payload, TTL=1800
        assert args[0].startswith("lockout:locked:")
        assert args[1] == "1"
        assert kwargs.get("ex") == 1800


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_clears_keys(self) -> None:
        redis = _make_redis()
        svc = AccountLockout(redis_client=redis, settings=_make_settings())

        await svc.reset("alice@example.com")

        redis.delete.assert_awaited_once()
        args = redis.delete.await_args.args
        # Both failed-key and locked-key passed in one DEL call
        assert any(a.startswith("lockout:failed:") for a in args)
        assert any(a.startswith("lockout:locked:") for a in args)


class TestRedisFailure:
    @pytest.mark.asyncio
    async def test_redis_failure_strict_mode_raises(self) -> None:
        """LOCKOUT_REQUIRE_REDIS=true → check raises RedisUnavailableError."""
        redis = _make_redis()
        redis.ttl = AsyncMock(side_effect=ConnectionError("boom"))
        svc = AccountLockout(
            redis_client=redis,
            settings=_make_settings(require_redis=True),
        )

        with pytest.raises(RedisUnavailableError):
            await svc.check("alice@example.com")

    @pytest.mark.asyncio
    async def test_redis_failure_lenient_mode_logs_and_passes(self, caplog) -> None:
        """LOCKOUT_REQUIRE_REDIS=false → check logs and returns (treat as not locked)."""
        redis = _make_redis()
        redis.ttl = AsyncMock(side_effect=ConnectionError("boom"))
        svc = AccountLockout(
            redis_client=redis,
            settings=_make_settings(require_redis=False),
        )

        # Should NOT raise
        await svc.check("alice@example.com")

    @pytest.mark.asyncio
    async def test_record_failure_redis_error_swallowed(self) -> None:
        """record_failure must always be best-effort (never raise)."""
        redis = _make_redis()
        # Make pipeline fail on enter
        bad_pipe = MagicMock()
        bad_pipe.__aenter__ = AsyncMock(side_effect=ConnectionError("boom"))
        bad_pipe.__aexit__ = AsyncMock(return_value=None)
        redis.pipeline = MagicMock(return_value=bad_pipe)
        svc = AccountLockout(redis_client=redis, settings=_make_settings())

        # Should NOT raise
        await svc.record_failure("alice@example.com")

    @pytest.mark.asyncio
    async def test_reset_redis_error_swallowed(self) -> None:
        redis = _make_redis()
        redis.delete = AsyncMock(side_effect=ConnectionError("boom"))
        svc = AccountLockout(redis_client=redis, settings=_make_settings())

        # Should NOT raise
        await svc.reset("alice@example.com")

    @pytest.mark.asyncio
    async def test_check_no_redis_strict_raises(self, monkeypatch) -> None:
        """When the Redis singleton is None and strict-mode is on, raise 503."""
        from src.core import redis as redis_module

        monkeypatch.setattr(redis_module, "redis_client", None)
        svc = AccountLockout(
            redis_client=None,
            settings=_make_settings(require_redis=True),
        )

        with pytest.raises(RedisUnavailableError):
            await svc.check("alice@example.com")
