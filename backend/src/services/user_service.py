"""Business-logic layer for user and invitation operations."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.models.user import Invitation, User, UserRole
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.refresh_token_repository import RefreshTokenRepository
from src.repositories.user_repository import UserRepository
from src.services.email_service import EmailService
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
        refresh_token_repo: RefreshTokenRepository,
        email_service: EmailService,
    ) -> None:
        self._users = user_repo
        self._invitations = invitation_repo
        self._pw = password_service
        self._refresh = refresh_token_repo
        self._email = email_service

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
    ) -> tuple[Invitation, str]:
        """Admin creates an invitation for a new user.

        Returns:
            A tuple of (invitation, raw_token).

        Raises:
            ForbiddenError: Caller is not an admin.
            ConflictError: Email already registered.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may invite users.")

        if await self._users.get_by_email(email):
            raise ConflictError(f"A user with email '{email}' already exists.")

        # Revoke any existing pending invitation for this email
        existing = await self._invitations.get_pending_by_email(email)
        if existing:
            await self._invitations.revoke_pending(existing.id)

        token = secrets.token_urlsafe()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(
            days=INVITATION_EXPIRY_DAYS,
        )

        invitation = await self._invitations.create(
            email=email.lower(),
            role=role,
            invited_by=admin.id,
            token=token_hash,
            expires_at=expires_at,
        )

        await self._email.send_invitation(email, token)

        return invitation, token

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
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invitation = await self._invitations.get_by_token(token_hash)
        if not invitation:
            raise NotFoundError("Invitation not found.")
        if invitation.accepted_at:
            raise ConflictError("Invitation already used.")
        if invitation.expires_at < datetime.now(UTC):
            raise ValidationError("Invitation has expired.")

        self._pw.validate_password_policy(password)
        hashed = self._pw.hash_password(password)

        user = await self._users.create(
            email=invitation.email,
            hashed_password=hashed,
            full_name=full_name,
            role=invitation.role,
        )
        await self._invitations.mark_accepted(token_hash)
        return user

    # ── admin operations ────────────────────────────────────────────

    async def deactivate_user(
        self, admin: User, target_id: uuid.UUID
    ) -> None:
        """Deactivate a user account. Admin-only.

        Raises:
            ForbiddenError: Caller is not an admin or tries to deactivate self.
            NotFoundError: Target user does not exist.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may deactivate users.")
        if admin.id == target_id:
            raise ForbiddenError("Cannot deactivate your own account.")
        result = await self._users.set_active(target_id, False)
        if result is None:
            raise NotFoundError("User not found.")
        await self._refresh.revoke_all_for_user(target_id)

    async def change_role(
        self, admin: User, target_id: uuid.UUID, new_role: UserRole
    ) -> User:
        """Change a user's role. Admin-only.

        Raises:
            ForbiddenError: Caller is not an admin or tries to change own role.
            NotFoundError: Target user does not exist.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may change roles.")
        if admin.id == target_id:
            raise ForbiddenError("Cannot change your own role.")
        target = await self._users.get_by_id(target_id)
        if target is None:
            raise NotFoundError("User not found.")
        target.role = new_role
        await self._users.update(target.id, role=new_role)
        return target

    async def list_users(
        self, admin: User, limit: int, offset: int
    ) -> tuple[list[User], int]:
        """List active users with total count. Admin-only.

        Returns:
            A tuple of (users, total_count).

        Raises:
            ForbiddenError: Caller is not an admin.
        """
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may list users.")
        users = list(await self._users.list_active(limit=limit, offset=offset))
        total = await self._users.count_active()
        return users, total
