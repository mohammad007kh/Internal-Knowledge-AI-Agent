"""Repository for Invitation data access."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import Invitation
from src.repositories.base_repository import BaseRepository


class InvitationRepository(BaseRepository[Invitation]):
    """Data-access layer for the ``invitations`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Invitation, session)

    async def get_by_token(self, token: str) -> Invitation | None:
        """Look up an invitation by its unique token."""
        stmt = select(Invitation).where(Invitation.token == token)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_accepted(self, token: str) -> Invitation | None:
        """Set ``accepted_at`` to the current UTC timestamp."""
        stmt = (
            update(Invitation)
            .where(Invitation.token == token)
            .values(accepted_at=datetime.now(timezone.utc))
            .returning(Invitation)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
