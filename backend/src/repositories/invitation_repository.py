"""Repository for Invitation data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.user import Invitation
from src.repositories.base_repository import BaseRepository


class InvitationRepository(BaseRepository[Invitation]):
    """Data-access layer for the ``invitations`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Invitation, session)

    async def get_by_token(self, token: str) -> Invitation | None:
        """Look up an invitation by its pre-hashed token (caller must hash)."""
        stmt = select(Invitation).where(Invitation.token == token)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, invitation_id: uuid.UUID) -> Invitation | None:
        """Return the invitation row for *invitation_id* (or ``None``)."""
        stmt = select(Invitation).where(Invitation.id == invitation_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[list[Invitation], int]:
        """Return (items, total) for pending (not accepted, not expired) invitations.

        Eager-loads ``invited_by_user`` so the router can expose
        ``invited_by_email`` without triggering lazy I/O.
        """
        now = datetime.now(UTC)
        base_where = (
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > now,
        )

        items_stmt = (
            select(Invitation)
            .where(*base_where)
            .options(selectinload(Invitation.invited_by_user))
            .order_by(Invitation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total_stmt = (
            select(func.count()).select_from(Invitation).where(*base_where)
        )

        items_result = await self._session.execute(items_stmt)
        total_result = await self._session.execute(total_stmt)
        return list(items_result.scalars().all()), int(total_result.scalar_one())

    async def revoke(self, invitation_id: uuid.UUID) -> None:
        """Hard-delete a pending invitation row.

        The ``Invitation`` model has no ``status`` column, so revocation is
        implemented as a hard delete. Callers must check that the invitation
        is still pending before invoking.
        """
        stmt = delete(Invitation).where(Invitation.id == invitation_id)
        await self._session.execute(stmt)
        await self._session.commit()

    async def mark_accepted(self, token: str) -> Invitation | None:
        """Set ``accepted_at`` to the current UTC timestamp (token must be pre-hashed)."""
        stmt = (
            update(Invitation)
            .where(Invitation.token == token)
            .values(accepted_at=datetime.now(UTC))
            .returning(Invitation)
        )
        result = await self._session.execute(stmt)
        invitation = result.scalar_one_or_none()
        await self._session.commit()
        return invitation

    async def get_pending_by_email(self, email: str) -> Invitation | None:
        """Return the pending (not accepted, not expired) invitation for *email*."""
        now = datetime.now(UTC)
        stmt = (
            select(Invitation)
            .where(Invitation.email == email.lower())
            .where(Invitation.accepted_at.is_(None))
            .where(Invitation.expires_at > now)
            .order_by(Invitation.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_pending(self, invitation_id: uuid.UUID) -> None:
        """Revoke a pending invitation by expiring it immediately."""
        stmt = (
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(expires_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)
        await self._session.commit()
