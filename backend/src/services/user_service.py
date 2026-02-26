"""Business-logic layer for user and invitation operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.models.user import Invitation, User, UserRole
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.user_repository import UserRepository
from src.services.password_service import PasswordService

INVITATION_EXPIRY_DAYS = 7


class UserService:
    """Coordinates user-related business rules.

    All user/invitation mutations flow through this service so that
    validation, hashing, and authorisation are enforced in one place.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        invitation_repo: InvitationRepository,
        password_service: PasswordService,
    ) -> None:
        self._users = user_repo
        self._invitations = invitation_repo
        self._pw = password_service

    # ── public registration ─────────────────────────────────────────

    async def register(
        self, email: str, password: str, full_name: str
    ) -> User:
        """Self-registration (open or first-user bootstrap).

        Raises:
            ValueError: Password does not meet policy.
            ConflictError: Email already registered.
        """
        self._pw.validate_password_policy(password)

        if await self._users.get_by_email(email):
            raise ConflictError(f"Email '{email}' is already registered.")

        hashed = self._pw.hash_password(password)
        return await self._users.create(
            email=email.lower(),
            hashed_password=hashed,
            full_name=full_name,
            role=UserRole.user,
        )

    # ── invitation flow ─────────────────────────────────────────────

    async def invite(
        self, admin: User, email: str, role: UserRole
    ) -> Invitation:
        """Admin creates an invitation for a new user.

        Raises:
            ForbiddenError: Caller is not an admin.
            ConflictError: Email already registered.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may invite users.")

        if await self._users.get_by_email(email):
            raise ConflictError(f"A user with email '{email}' already exists.")

        token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=INVITATION_EXPIRY_DAYS,
        )

        return await self._invitations.create(
            email=email.lower(),
            role=role,
            invited_by=admin.id,
            token=token,
            expires_at=expires_at,
        )

    async def accept_invitation(
        self, token: str, full_name: str, password: str
    ) -> User:
        """Redeem a valid invitation and create the user account.

        Raises:
            NotFoundError: Token does not exist.
            ConflictError: Token already used.
            ValidationError: Token expired.
            ValueError: Password does not meet policy.
        """
        invitation = await self._invitations.get_by_token(token)
        if not invitation:
            raise NotFoundError("Invitation not found.")
        if invitation.accepted_at:
            raise ConflictError("Invitation already used.")
        if invitation.expires_at < datetime.now(timezone.utc):
            raise ValidationError("Invitation has expired.")

        self._pw.validate_password_policy(password)
        hashed = self._pw.hash_password(password)

        user = await self._users.create(
            email=invitation.email,
            hashed_password=hashed,
            full_name=full_name,
            role=invitation.role,
        )
        await self._invitations.mark_accepted(token)
        return user

    # ── admin operations ────────────────────────────────────────────

    async def deactivate_user(
        self, admin: User, target_id: uuid.UUID
    ) -> None:
        """Deactivate a user account. Admin-only.

        Raises:
            ForbiddenError: Caller is not an admin.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may deactivate users.")
        await self._users.set_active(target_id, False)

    async def list_users(
        self, admin: User, limit: int, offset: int
    ) -> list[User]:
        """List active users. Admin-only.

        Raises:
            ForbiddenError: Caller is not an admin.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may list users.")
        return list(await self._users.list_active(limit=limit, offset=offset))
