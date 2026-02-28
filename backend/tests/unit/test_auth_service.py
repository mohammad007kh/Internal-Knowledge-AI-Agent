"""Unit tests for :class:`AuthService`.

Covers all seven public methods (22 test cases):

| Class                      | # | Methods under test            |
|----------------------------|---|-------------------------------|
| TestLogin                  | 5 | login (happy, bad-email,      |
|                            |   |  bad-password, disabled, mcp) |
| TestRefresh                | 4 | refresh (happy, bad-token,    |
|                            |   |  missing-user, disabled)      |
| TestLogout                 | 2 | logout (happy, unknown-token) |
| TestAcceptInvitation       | 2 | accept_invitation (happy,     |
|                            |   |  weak-password)               |
| TestRequestPasswordReset   | 3 | request_password_reset        |
|                            |   |  (happy, unknown, inactive)   |
| TestConfirmPasswordReset   | 4 | confirm_password_reset        |
|                            |   |  (happy, bad-token, no-user,  |
|                            |   |  weak-password)               |
| TestChangePassword         | 4 | change_password (happy,       |
|                            |   |  not-found, wrong-current,    |
|                            |   |  weak-new)                    |
"""

from __future__ import annotations

import enum
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from src.services.auth_service import AuthService

# ------------------------------------------------------------------ #
# Constants                                                           #
# ------------------------------------------------------------------ #

VALID_PASSWORD = "Str0ng!Pass"
HASHED = "$2b$12$fakehashvalue"
FAKE_ACCESS = "eyJ.access.token"
FAKE_REFRESH = "url-safe-refresh-token"
FAKE_RESET = "url-safe-reset-token"


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


class _FakeRole(enum.StrEnum):
    admin = "admin"
    user = "user"


def _make_user(
    *,
    role: _FakeRole = _FakeRole.user,
    email: str = "alice@example.com",
    is_active: bool = True,
    must_change_password: bool = False,
) -> SimpleNamespace:
    """Lightweight stand-in for a ``User`` ORM instance."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=email,
        full_name="Alice",
        role=role,
        is_active=is_active,
        hashed_password=HASHED,
        must_change_password=must_change_password,
    )


def _make_refresh_record(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    """Stand-in for a ``UserRefreshToken`` ORM row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


def _make_reset_record(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    """Stand-in for a ``PasswordResetToken`` ORM row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
    )


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #


@pytest.fixture()
def mocks():
    """Return ``(user_repo, refresh_repo, user_service, password_service)``."""
    user_repo = MagicMock()
    user_repo.get_by_email = AsyncMock(return_value=None)
    user_repo.get_by_id = AsyncMock(return_value=None)
    user_repo.update = AsyncMock(return_value=None)

    refresh_repo = MagicMock()
    refresh_repo.get_valid_by_token = AsyncMock(return_value=None)
    refresh_repo.create_refresh_token = AsyncMock(return_value=None)
    refresh_repo.revoke = AsyncMock(return_value=None)
    refresh_repo.revoke_all_for_user = AsyncMock(return_value=None)
    refresh_repo.create_password_reset_token = AsyncMock(return_value=None)
    refresh_repo.get_valid_reset_token = AsyncMock(return_value=None)
    refresh_repo.consume_reset_token = AsyncMock(return_value=None)

    user_service = MagicMock()
    user_service.accept_invitation = AsyncMock(return_value=None)

    password_service = MagicMock()
    password_service.verify_password = MagicMock(return_value=True)
    password_service.hash_password = MagicMock(return_value=HASHED)
    password_service.validate_password_policy = MagicMock(return_value=None)

    return user_repo, refresh_repo, user_service, password_service


@pytest.fixture()
def service(mocks):
    """Construct an ``AuthService`` wired to the mock tuple."""
    user_repo, refresh_repo, user_service, password_service = mocks
    return AuthService(user_repo, refresh_repo, user_service, password_service)


# ================================================================== #
# TestLogin                                                           #
# ================================================================== #


class TestLogin:
    """Tests for ``AuthService.login``."""

    @pytest.mark.asyncio
    @patch("src.services.auth_service.secrets.token_urlsafe", return_value=FAKE_REFRESH)
    @patch("src.services.auth_service.create_access_token", return_value=FAKE_ACCESS)
    async def test_success(self, _mock_cat, _mock_secret, mocks, service):
        user = _make_user()
        user_repo, refresh_repo, _, password_svc = mocks
        user_repo.get_by_email.return_value = user
        password_svc.verify_password.return_value = True

        access, refresh, mcp = await service.login("alice@example.com", VALID_PASSWORD)

        assert access == FAKE_ACCESS
        assert refresh == FAKE_REFRESH
        assert mcp is False
        refresh_repo.create_refresh_token.assert_awaited_once_with(user.id, FAKE_REFRESH)

    @pytest.mark.asyncio
    async def test_unknown_email(self, mocks, service):
        user_repo, *_ = mocks
        user_repo.get_by_email.return_value = None

        with pytest.raises(UnauthorizedError, match="Invalid email or password"):
            await service.login("unknown@example.com", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_wrong_password(self, mocks, service):
        user = _make_user()
        user_repo, _, _, password_svc = mocks
        user_repo.get_by_email.return_value = user
        password_svc.verify_password.return_value = False

        with pytest.raises(UnauthorizedError, match="Invalid email or password"):
            await service.login("alice@example.com", "wrong")

    @pytest.mark.asyncio
    async def test_disabled_account(self, mocks, service):
        user = _make_user(is_active=False)
        user_repo, _, _, password_svc = mocks
        user_repo.get_by_email.return_value = user
        password_svc.verify_password.return_value = True

        with pytest.raises(ForbiddenError, match="Account is disabled"):
            await service.login("alice@example.com", VALID_PASSWORD)

    @pytest.mark.asyncio
    @patch("src.services.auth_service.secrets.token_urlsafe", return_value=FAKE_REFRESH)
    @patch("src.services.auth_service.create_access_token", return_value=FAKE_ACCESS)
    async def test_must_change_password_flag(self, _a, _b, mocks, service):
        user = _make_user(must_change_password=True)
        user_repo, _, _, password_svc = mocks
        user_repo.get_by_email.return_value = user
        password_svc.verify_password.return_value = True

        _, _, mcp = await service.login("alice@example.com", VALID_PASSWORD)

        assert mcp is True


# ================================================================== #
# TestRefresh                                                         #
# ================================================================== #


class TestRefresh:
    """Tests for ``AuthService.refresh``."""

    @pytest.mark.asyncio
    @patch("src.services.auth_service.secrets.token_urlsafe", return_value=FAKE_REFRESH)
    @patch("src.services.auth_service.create_access_token", return_value=FAKE_ACCESS)
    async def test_success(self, _mock_cat, _mock_secret, mocks, service):
        user = _make_user()
        user_repo, refresh_repo, _, _ = mocks
        record = _make_refresh_record(user.id)
        refresh_repo.get_valid_by_token.return_value = record
        user_repo.get_by_id.return_value = user

        access, refresh, mcp = await service.refresh("old-token")

        assert access == FAKE_ACCESS
        assert refresh == FAKE_REFRESH
        refresh_repo.revoke.assert_awaited_once_with(record.id)
        refresh_repo.create_refresh_token.assert_awaited_once_with(user.id, FAKE_REFRESH)

    @pytest.mark.asyncio
    async def test_invalid_token(self, mocks, service):
        refresh_repo = mocks[1]
        refresh_repo.get_valid_by_token.return_value = None

        with pytest.raises(UnauthorizedError, match="Invalid or expired refresh token"):
            await service.refresh("bad-token")

    @pytest.mark.asyncio
    async def test_user_not_found(self, mocks, service):
        user_repo, refresh_repo, _, _ = mocks
        record = _make_refresh_record()
        refresh_repo.get_valid_by_token.return_value = record
        user_repo.get_by_id.return_value = None

        with pytest.raises(UnauthorizedError, match="User not found"):
            await service.refresh("some-token")

    @pytest.mark.asyncio
    async def test_disabled_account(self, mocks, service):
        user = _make_user(is_active=False)
        user_repo, refresh_repo, _, _ = mocks
        record = _make_refresh_record(user.id)
        refresh_repo.get_valid_by_token.return_value = record
        user_repo.get_by_id.return_value = user

        with pytest.raises(ForbiddenError, match="Account is disabled"):
            await service.refresh("some-token")


# ================================================================== #
# TestLogout                                                          #
# ================================================================== #


class TestLogout:
    """Tests for ``AuthService.logout``."""

    @pytest.mark.asyncio
    async def test_success(self, mocks, service):
        refresh_repo = mocks[1]
        record = _make_refresh_record()
        refresh_repo.get_valid_by_token.return_value = record

        await service.logout("some-token")

        refresh_repo.revoke.assert_awaited_once_with(record.id)

    @pytest.mark.asyncio
    async def test_unknown_token_is_noop(self, mocks, service):
        refresh_repo = mocks[1]
        refresh_repo.get_valid_by_token.return_value = None

        await service.logout("unknown-token")  # should not raise

        refresh_repo.revoke.assert_not_awaited()


# ================================================================== #
# TestAcceptInvitation                                                #
# ================================================================== #


class TestAcceptInvitation:
    """Tests for ``AuthService.accept_invitation``."""

    @pytest.mark.asyncio
    @patch("src.services.auth_service.secrets.token_urlsafe", return_value=FAKE_REFRESH)
    @patch("src.services.auth_service.create_access_token", return_value=FAKE_ACCESS)
    async def test_success(self, _a, _b, mocks, service):
        user = _make_user()
        _, _, user_service, password_svc = mocks
        user_service.accept_invitation.return_value = user
        password_svc.validate_password_policy.return_value = None

        access, refresh, mcp = await service.accept_invitation(
            "inv-token", "Alice", VALID_PASSWORD
        )

        assert access == FAKE_ACCESS
        assert refresh == FAKE_REFRESH
        password_svc.validate_password_policy.assert_called_once_with(VALID_PASSWORD)
        user_service.accept_invitation.assert_awaited_once_with(
            "inv-token", "Alice", VALID_PASSWORD
        )

    @pytest.mark.asyncio
    async def test_weak_password_rejected(self, mocks, service):
        _, _, _, password_svc = mocks
        password_svc.validate_password_policy.side_effect = ValueError("too weak")

        with pytest.raises(ValueError, match="too weak"):
            await service.accept_invitation("inv-token", "Alice", "weak")


# ================================================================== #
# TestRequestPasswordReset                                            #
# ================================================================== #


class TestRequestPasswordReset:
    """Tests for ``AuthService.request_password_reset``."""

    @pytest.mark.asyncio
    @patch("src.services.auth_service.secrets.token_urlsafe", return_value=FAKE_RESET)
    async def test_success(self, _mock_secret, mocks, service):
        user = _make_user()
        user_repo, refresh_repo, _, _ = mocks
        user_repo.get_by_email.return_value = user

        result = await service.request_password_reset("alice@example.com")

        assert result == FAKE_RESET
        refresh_repo.create_password_reset_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_email_returns_none(self, mocks, service):
        user_repo = mocks[0]
        user_repo.get_by_email.return_value = None

        result = await service.request_password_reset("ghost@example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_user_returns_none(self, mocks, service):
        user = _make_user(is_active=False)
        user_repo = mocks[0]
        user_repo.get_by_email.return_value = user

        result = await service.request_password_reset("alice@example.com")

        assert result is None


# ================================================================== #
# TestConfirmPasswordReset                                            #
# ================================================================== #


class TestConfirmPasswordReset:
    """Tests for ``AuthService.confirm_password_reset``."""

    @pytest.mark.asyncio
    async def test_success(self, mocks, service):
        user = _make_user()
        user_repo, refresh_repo, _, password_svc = mocks
        record = _make_reset_record(user.id)
        refresh_repo.get_valid_reset_token.return_value = record
        user_repo.get_by_id.return_value = user

        await service.confirm_password_reset("reset-tok", VALID_PASSWORD)

        password_svc.validate_password_policy.assert_called_once_with(VALID_PASSWORD)
        password_svc.hash_password.assert_called_once_with(VALID_PASSWORD)
        user_repo.update.assert_awaited_once_with(
            user.id, hashed_password=HASHED, must_change_password=False
        )
        refresh_repo.consume_reset_token.assert_awaited_once_with(record.id)
        refresh_repo.revoke_all_for_user.assert_awaited_once_with(user.id)

    @pytest.mark.asyncio
    async def test_invalid_token(self, mocks, service):
        refresh_repo = mocks[1]
        refresh_repo.get_valid_reset_token.return_value = None

        with pytest.raises(UnauthorizedError, match="Invalid or expired reset token"):
            await service.confirm_password_reset("bad-tok", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_user_not_found(self, mocks, service):
        user_repo, refresh_repo, _, _ = mocks
        record = _make_reset_record()
        refresh_repo.get_valid_reset_token.return_value = record
        user_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError, match="User not found"):
            await service.confirm_password_reset("some-tok", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_weak_password_rejected(self, mocks, service):
        _, _, _, password_svc = mocks
        password_svc.validate_password_policy.side_effect = ValueError("too weak")

        with pytest.raises(ValueError, match="too weak"):
            await service.confirm_password_reset("some-tok", "weak")


# ================================================================== #
# TestChangePassword                                                  #
# ================================================================== #


class TestChangePassword:
    """Tests for ``AuthService.change_password``."""

    @pytest.mark.asyncio
    async def test_success(self, mocks, service):
        user = _make_user()
        user_repo, refresh_repo, _, password_svc = mocks
        user_repo.get_by_id.return_value = user

        await service.change_password(user.id, "OldPass!1", VALID_PASSWORD)

        password_svc.validate_password_policy.assert_called_once_with(VALID_PASSWORD)
        password_svc.verify_password.assert_called_once_with("OldPass!1", HASHED)
        password_svc.hash_password.assert_called_once_with(VALID_PASSWORD)
        user_repo.update.assert_awaited_once_with(
            user.id, hashed_password=HASHED, must_change_password=False
        )
        refresh_repo.revoke_all_for_user.assert_awaited_once_with(user.id)

    @pytest.mark.asyncio
    async def test_user_not_found(self, mocks, service):
        user_repo = mocks[0]
        user_repo.get_by_id.return_value = None

        with pytest.raises(NotFoundError, match="User not found"):
            await service.change_password(uuid.uuid4(), "old", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_wrong_current_password(self, mocks, service):
        user = _make_user()
        user_repo, _, _, password_svc = mocks
        user_repo.get_by_id.return_value = user
        password_svc.verify_password.return_value = False

        with pytest.raises(UnauthorizedError, match="Current password is incorrect"):
            await service.change_password(user.id, "wrong", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_weak_new_password_rejected(self, mocks, service):
        _, _, _, password_svc = mocks
        password_svc.validate_password_policy.side_effect = ValueError("too weak")

        with pytest.raises(ValueError, match="too weak"):
            await service.change_password(uuid.uuid4(), "old", "weak")
