"""Integration tests for per-email-hash account lockout (Slice D).

These tests build a dedicated FastAPI ASGI client whose AuthService is wired
with a real :class:`AccountLockout` backed by an in-process async Redis
double, so they validate the full HTTP code path (route → service →
lockout → exception handler → 423 response) without requiring a running
Redis.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Minimal in-process async Redis double
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, redis: "_FakeAsyncRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def zremrangebyscore(self, key: str, lo: float, hi: float) -> "_FakePipeline":
        self._ops.append(("zremrangebyscore", (key, lo, hi), {}))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> "_FakePipeline":
        self._ops.append(("zadd", (key, mapping), {}))
        return self

    def zcard(self, key: str) -> "_FakePipeline":
        self._ops.append(("zcard", (key,), {}))
        return self

    def expire(self, key: str, ttl: int) -> "_FakePipeline":
        self._ops.append(("expire", (key, ttl), {}))
        return self

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, args, _kwargs in self._ops:
            if op == "zremrangebyscore":
                key, lo, hi = args
                bucket = self._redis._zsets.setdefault(key, {})
                removed = [m for m, score in bucket.items() if lo <= score <= hi]
                for m in removed:
                    bucket.pop(m, None)
                results.append(len(removed))
            elif op == "zadd":
                key, mapping = args
                bucket = self._redis._zsets.setdefault(key, {})
                bucket.update(mapping)
                results.append(len(mapping))
            elif op == "zcard":
                key = args[0]
                results.append(len(self._redis._zsets.get(key, {})))
            elif op == "expire":
                # In-memory: ignore TTLs for sorted-sets in tests.
                results.append(1)
        self._ops.clear()
        return results


class _FakeAsyncRedis:
    """In-process double of redis.asyncio.Redis exposing only the surface
    that AccountLockout uses."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}
        self._strings: dict[str, tuple[str, float | None]] = {}  # key → (val, expires_at)

    def pipeline(self, transaction: bool = True) -> _FakePipeline:  # noqa: ARG002
        return _FakePipeline(self)

    async def ttl(self, key: str) -> int:
        rec = self._strings.get(key)
        if rec is None:
            return -2
        _val, expires_at = rec
        if expires_at is None:
            return -1
        remaining = expires_at - time.time()
        if remaining <= 0:
            self._strings.pop(key, None)
            return -2
        return int(remaining)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
    ) -> bool:
        expires_at = time.time() + ex if ex else None
        self._strings[key] = (value, expires_at)
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._strings:
                del self._strings[k]
                count += 1
            if k in self._zsets:
                del self._zsets[k]
                count += 1
        return count


# ---------------------------------------------------------------------------
# Custom client with lockout-enabled AuthService
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def fake_redis() -> _FakeAsyncRedis:
    return _FakeAsyncRedis()


@pytest_asyncio.fixture()
async def lockout_client(db_session, fake_redis):  # type: ignore[no-untyped-def]
    """ASGI client whose AuthService is wired with a real AccountLockout.

    The lockout uses an in-process Redis double, so we exercise the full
    request → service → lockout → handler path (including the 423 response
    + ``Retry-After`` header) without requiring an actual Redis instance.
    """
    from httpx import ASGITransport, AsyncClient

    from src.api.v1.auth import _get_auth_service
    from src.core.database import get_db
    from src.main import create_app
    from src.repositories.refresh_token_repository import RefreshTokenRepository
    from src.repositories.user_repository import UserRepository
    from src.services.account_lockout import AccountLockout
    from src.services.auth_service import AuthService
    from src.services.email_service import EmailService
    from src.services.password_service import PasswordService
    from src.services.user_service import UserService
    from src.repositories.invitation_repository import InvitationRepository
    from types import SimpleNamespace

    # Use a short-lockout config so the "lock expires" test runs in <2s.
    lockout_settings = SimpleNamespace(
        LOCKOUT_ENABLED=True,
        LOCKOUT_REQUIRE_REDIS=True,
        LOCKOUT_MAX_FAILS=3,
        LOCKOUT_WINDOW_SECS=60,
        LOCKOUT_DURATION_SECS=1,
    )
    lockout = AccountLockout(redis_client=fake_redis, settings=lockout_settings)

    def _make_user_svc() -> UserService:
        return UserService(
            user_repo=UserRepository(session=db_session),
            invitation_repo=InvitationRepository(session=db_session),
            password_service=PasswordService(),
            refresh_token_repo=RefreshTokenRepository(session=db_session),
            email_service=EmailService(),
        )

    def _make_auth_svc() -> AuthService:
        return AuthService(
            user_repo=UserRepository(session=db_session),
            refresh_repo=RefreshTokenRepository(session=db_session),
            user_service=_make_user_svc(),
            password_service=PasswordService(),
            session=db_session,
            lockout=lockout,
        )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[_get_auth_service] = _make_auth_svc

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLockout:
    async def test_n_failed_logins_then_locked(
        self, lockout_client: "AsyncClient", admin_user
    ) -> None:
        """4th attempt (after 3 wrong-password failures) returns 423."""
        for _ in range(3):
            resp = await lockout_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "WRONG"},
            )
            assert resp.status_code == 401

        resp = await lockout_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "WRONG"},
        )
        assert resp.status_code == 423
        body = resp.json()
        assert body["status"] == 423
        assert "retry_after_seconds" in body["extra"]
        assert "Retry-After" in resp.headers

    async def test_correct_password_after_lock_still_returns_423(
        self, lockout_client: "AsyncClient", admin_user
    ) -> None:
        """While locked, even the correct password is rejected with 423."""
        # Burn through threshold
        for _ in range(4):
            await lockout_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "WRONG"},
            )
        resp = await lockout_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        assert resp.status_code == 423

    async def test_lock_expires_after_duration(
        self, lockout_client: "AsyncClient", admin_user
    ) -> None:
        """After LOCKOUT_DURATION_SECS=1 elapses, login succeeds again."""
        import asyncio

        for _ in range(4):
            await lockout_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "WRONG"},
            )
        # Confirm locked
        resp = await lockout_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        assert resp.status_code == 423

        # Wait for the 1-second TTL to expire
        await asyncio.sleep(1.5)

        resp = await lockout_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        assert resp.status_code == 200

    async def test_successful_login_resets_counter(
        self, lockout_client: "AsyncClient", admin_user
    ) -> None:
        """A successful login mid-window clears the failure counter."""
        # 2 failures (one short of the 3-fail threshold)
        for _ in range(2):
            await lockout_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "WRONG"},
            )

        # Successful login resets
        resp = await lockout_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        assert resp.status_code == 200

        # 2 more failures should NOT lock (counter was reset)
        for _ in range(2):
            resp = await lockout_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "WRONG"},
            )
            assert resp.status_code == 401
