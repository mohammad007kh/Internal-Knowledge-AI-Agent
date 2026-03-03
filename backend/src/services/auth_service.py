"""Authentication service – login, token refresh, logout, password flows.

Orchestrates :class:`UserRepository`, :class:`RefreshTokenRepository`,
:class:`UserService`, and :class:`PasswordService` to implement the full
authentication lifecycle.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError, UnauthorizedError
from src.core.security import create_access_token
from src.repositories.refresh_token_repository import RefreshTokenRepository
from src.repositories.user_repository import UserRepository
from src.services.password_service import PasswordService
from src.services.user_service import UserService

if TYPE_CHECKING:
    from src.models.user import User


class AuthService:
    """High-level authentication and credential-management service."""

    def __init__(
        self,
        user_repo: UserRepository,
        refresh_repo: RefreshTokenRepository,
        user_service: UserService,
        password_service: PasswordService,
    ) -> None:
        self._user_repo = user_repo
        self._refresh_repo = refresh_repo
        self._user_service = user_service
        self._password_svc = password_service

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def login(
        self, email: str, password: str
    ) -> tuple[str, str, bool]:
        """Authenticate with *email* / *password*.

        Returns ``(access_token, raw_refresh_token, must_change_password)``.

        Raises:
            UnauthorizedError: bad credentials.
            ForbiddenError: account disabled.
        """
        user = await self._user_repo.get_by_email(email)
        if user is None or not self._password_svc.verify_password(
            password, user.hashed_password
        ):
            raise UnauthorizedError("Invalid email or password")

        if not user.is_active:
            raise ForbiddenError("Account is disabled")

        return await self._issue_tokens(user)

    async def refresh(
        self, raw_token: str
    ) -> tuple[str, str, bool]:
        """Rotate a refresh token.

        Returns a fresh ``(access_token, raw_refresh_token, must_change_password)``
        tuple after revoking the old refresh token.

        Raises:
            UnauthorizedError: token invalid / expired / revoked, or user missing.
            ForbiddenError: account disabled.
        """
        record = await self._refresh_repo.get_valid_by_token(raw_token)
        if record is None:
            raise UnauthorizedError("Invalid or expired refresh token")

        user = await self._user_repo.get_by_id(record.user_id)
        if user is None:
            raise UnauthorizedError("User not found")

        if not user.is_active:
            raise ForbiddenError("Account is disabled")

        await self._refresh_repo.revoke(record.id)
        return await self._issue_tokens(user)

    async def logout(self, raw_token: str) -> None:
        """Revoke a refresh token.  No-op when the token is unknown."""
        record = await self._refresh_repo.get_valid_by_token(raw_token)
        if record is not None:
            await self._refresh_repo.revoke(record.id)

    async def accept_invitation(
        self,
        invitation_token: str,
        full_name: str,
        password: str,
    ) -> tuple[str, str, bool]:
        """Accept an invitation, creating an account and issuing tokens.

        Returns ``(access_token, raw_refresh_token, must_change_password)``.
        """
        self._password_svc.validate_password_policy(password)
        user = await self._user_service.accept_invitation(
            invitation_token, full_name, password
        )
        return await self._issue_tokens(user)

    async def request_password_reset(self, email: str) -> str | None:
        """Start a password-reset flow.

        Returns the raw reset token when the user exists and is active,
        otherwise ``None`` (to avoid user-enumeration).
        """
        user = await self._user_repo.get_by_email(email)
        if user is None or not user.is_active:
            return None

        raw = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        await self._refresh_repo.create_password_reset_token(
            user.id, raw, expires_at
        )
        return raw

    async def confirm_password_reset(
        self, raw_token: str, new_password: str
    ) -> None:
        """Set a new password using a valid reset token.

        Raises:
            UnauthorizedError: token invalid / expired / consumed.
            NotFoundError: user no longer exists.
        """
        self._password_svc.validate_password_policy(new_password)

        record = await self._refresh_repo.get_valid_reset_token(raw_token)
        if record is None:
            raise UnauthorizedError("Invalid or expired reset token")

        user = await self._user_repo.get_by_id(record.user_id)
        if user is None:
            raise NotFoundError("User not found")

        hashed = self._password_svc.hash_password(new_password)
        await self._user_repo.update(
            user.id,
            hashed_password=hashed,
            must_change_password=False,
        )
        await self._refresh_repo.consume_reset_token(record.id)
        await self._refresh_repo.revoke_all_for_user(user.id)

    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """Change password for an authenticated user.

        Raises:
            NotFoundError: user not found.
            UnauthorizedError: current password wrong.
        """
        self._password_svc.validate_password_policy(new_password)

        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        if not self._password_svc.verify_password(
            current_password, user.hashed_password
        ):
            raise UnauthorizedError("Current password is incorrect")

        hashed = self._password_svc.hash_password(new_password)
        await self._user_repo.update(
            user.id,
            hashed_password=hashed,
            must_change_password=False,
        )
        await self._refresh_repo.revoke_all_for_user(user.id)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    async def _issue_tokens(self, user: User) -> tuple[str, str, bool]:
        """Create an access + refresh token pair for *user*.

        Returns ``(access_token, raw_refresh_token, must_change_password)``.
        """
        access_token = create_access_token(
            {"sub": str(user.id), "role": user.role.value}
        )
        raw_refresh = secrets.token_urlsafe(32)
        await self._refresh_repo.create_refresh_token(user.id, raw_refresh)
        return access_token, raw_refresh, user.must_change_password
