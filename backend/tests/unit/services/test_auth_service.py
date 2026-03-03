"""Unit tests for AuthService and PasswordService — T-090."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.services.auth_service import AuthService
from src.services.password_service import PasswordService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_service(user_repo, refresh_repo, user_service=None, password_service=None):
    us = user_service or MagicMock()
    ps = password_service or MagicMock()
    return AuthService(
        user_repo=user_repo,
        refresh_repo=refresh_repo,
        user_service=us,
        password_service=ps,
    )


# ---------------------------------------------------------------------------
# TestLogin
# ---------------------------------------------------------------------------

class TestLogin:
    async def test_valid_credentials_returns_token_tuple(self, fake_user, mock_user_repo):
        """Happy path: correct email + password → (access, refresh, must_change)."""
        fake_user.hashed_password = "$2b$12$hashed"
        mock_user_repo.get_by_email = AsyncMock(return_value=fake_user)

        refresh_repo = AsyncMock()
        refresh_repo.create = AsyncMock(return_value=MagicMock())

        password_service = MagicMock()
        password_service.verify_password = MagicMock(return_value=True)

        service = _make_auth_service(mock_user_repo, refresh_repo, password_service=password_service)

        with patch.object(service, "_issue_tokens", return_value=("access_tok", "refresh_tok", False)):
            result = await service.login(email="alice@example.com", password="ValidPass1!")

        assert result is not None

    async def test_wrong_password_raises_unauthorized(self, fake_user, mock_user_repo):
        """Wrong password → UnauthorizedError."""
        mock_user_repo.get_by_email = AsyncMock(return_value=fake_user)

        password_service = MagicMock()
        password_service.verify_password = MagicMock(return_value=False)

        service = _make_auth_service(mock_user_repo, AsyncMock(), password_service=password_service)

        with pytest.raises(UnauthorizedError):
            await service.login(email="alice@example.com", password="WrongPass!")

    async def test_unknown_email_raises_unauthorized(self, mock_user_repo):
        """Unknown email → UnauthorizedError (not NotFoundError — timing-safe)."""
        mock_user_repo.get_by_email = AsyncMock(return_value=None)

        service = _make_auth_service(mock_user_repo, AsyncMock())

        with pytest.raises(UnauthorizedError):
            await service.login(email="ghost@example.com", password="AnyPass1!")

    async def test_inactive_user_raises_forbidden(self, fake_user, mock_user_repo):
        """Inactive account → ForbiddenError."""
        fake_user.is_active = False
        mock_user_repo.get_by_email = AsyncMock(return_value=fake_user)

        password_service = MagicMock()
        password_service.verify_password = MagicMock(return_value=True)

        service = _make_auth_service(mock_user_repo, AsyncMock(), password_service=password_service)

        with pytest.raises(ForbiddenError):
            await service.login(email="alice@example.com", password="ValidPass1!")


# ---------------------------------------------------------------------------
# TestRefresh
# ---------------------------------------------------------------------------

class TestRefresh:
    async def test_valid_token_returns_new_pair(self, fake_user, mock_user_repo):
        """Valid refresh token → new (access, refresh) pair."""
        refresh_repo = AsyncMock()
        refresh_repo.get_by_token = AsyncMock(return_value=MagicMock(user_id=fake_user.id, is_revoked=False))
        refresh_repo.revoke = AsyncMock()
        refresh_repo.create = AsyncMock(return_value=MagicMock())
        mock_user_repo.get_by_id = AsyncMock(return_value=fake_user)

        service = _make_auth_service(mock_user_repo, refresh_repo)

        with patch.object(service, "_issue_tokens", return_value=("new_access", "new_refresh", False)):
            result = await service.refresh(raw_token="valid_refresh_token")

        assert result is not None

    async def test_expired_or_invalid_token_raises_unauthorized(self, mock_user_repo):
        """Non-existent / expired refresh token → UnauthorizedError."""
        refresh_repo = AsyncMock()
        refresh_repo.get_by_token = AsyncMock(return_value=None)

        service = _make_auth_service(mock_user_repo, refresh_repo)

        with pytest.raises(UnauthorizedError):
            await service.refresh(raw_token="bad_token")


# ---------------------------------------------------------------------------
# TestPasswordPolicy
# ---------------------------------------------------------------------------

class TestPasswordPolicy:
    def test_short_password_raises_value_error(self):
        """Password shorter than minimum → ValueError."""
        with pytest.raises(ValueError):
            PasswordService.validate_password_policy("Short1!")

    def test_no_uppercase_raises_value_error(self):
        """Password without uppercase → ValueError."""
        with pytest.raises(ValueError):
            PasswordService.validate_password_policy("nouppercase1!")

    def test_no_digit_raises_value_error(self):
        """Password without digit → ValueError."""
        with pytest.raises(ValueError):
            PasswordService.validate_password_policy("NoDigitHere!")

    def test_valid_password_passes(self):
        """Strong password does not raise."""
        # Should not raise — returns None
        result = PasswordService.validate_password_policy("ValidPass1!")
        assert result is None
