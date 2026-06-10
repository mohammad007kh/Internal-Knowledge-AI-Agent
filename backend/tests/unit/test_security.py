"""Unit tests for src.core.security.

All database interactions are mocked — no real DB is required.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import jwt

from src.core.config import settings
from src.core.exceptions import UnauthorizedError
from src.core.security import (
    ALGORITHM,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    revoke_refresh_token,
    set_refresh_cookie,
    verify_access_token,
    verify_refresh_token,
)


class TestCreateAccessToken:
    def test_returns_decodable_jwt(self):
        token = create_access_token({"sub": "user-123"})
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_expired_token_raises(self):
        # Craft a token whose expiry is already in the past.
        data = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(UTC) - timedelta(seconds=1),
            "type": "access",
        }
        token = jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(UnauthorizedError):
            verify_access_token(token)

    def test_tampered_token_raises(self):
        token = create_access_token({"sub": "user-123"})
        tampered = token + "x"
        with pytest.raises(UnauthorizedError):
            verify_access_token(tampered)

    def test_wrong_type_raises(self):
        data = {
            "sub": "user-123",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "type": "refresh",
        }
        token = jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(UnauthorizedError, match="Invalid token type"):
            verify_access_token(token)


class TestCreateRefreshToken:
    def test_returns_uuid_string(self):
        token = create_refresh_token()
        # uuid.UUID() raises ValueError for non-UUID strings.
        uuid.UUID(token)
        assert isinstance(token, str)

    def test_each_call_returns_unique_value(self):
        assert create_refresh_token() != create_refresh_token()


class TestVerifyRefreshToken:
    @pytest.mark.asyncio
    async def test_unknown_token_raises(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(UnauthorizedError, match="not found"):
            await verify_refresh_token("unknown-token", db)

    @pytest.mark.asyncio
    async def test_revoked_token_raises(self):
        db = AsyncMock()
        row = MagicMock()
        row.revoked_at = datetime.now(UTC)
        row.expires_at = datetime.now(UTC) + timedelta(days=7)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(UnauthorizedError, match="revoked"):
            await verify_refresh_token("some-token", db)

    @pytest.mark.asyncio
    async def test_expired_token_raises(self):
        db = AsyncMock()
        row = MagicMock()
        row.revoked_at = None
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(UnauthorizedError, match="expired"):
            await verify_refresh_token("some-token", db)

    @pytest.mark.asyncio
    async def test_valid_token_returns_row(self):
        db = AsyncMock()
        row = MagicMock()
        row.revoked_at = None
        row.expires_at = datetime.now(UTC) + timedelta(days=7)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        result = await verify_refresh_token("valid-token", db)
        assert result is row


class TestRevokeRefreshToken:
    @pytest.mark.asyncio
    async def test_sets_revoked_at(self):
        db = AsyncMock()
        row = MagicMock()
        row.revoked_at = None
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        await revoke_refresh_token("some-token", db)

        assert row.revoked_at is not None
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_for_missing_token(self):
        """revoke_refresh_token should not raise if token is not found."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        # Should complete without error.
        await revoke_refresh_token("ghost-token", db)
        db.flush.assert_not_awaited()


class TestCookieHelpers:
    def test_set_refresh_cookie_sets_correct_attributes(self):
        response = MagicMock()
        set_refresh_cookie(response, "my-token")
        response.set_cookie.assert_called_once_with(
            key="refresh_token",
            value="my-token",
            httponly=True,
            samesite="strict",
            secure=settings.COOKIE_SECURE,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            path="/api/v1/auth",
        )

    def test_clear_refresh_cookie_deletes_cookie(self):
        response = MagicMock()
        clear_refresh_cookie(response)
        response.delete_cookie.assert_called_once_with(
            key="refresh_token", path="/api/v1/auth"
        )
