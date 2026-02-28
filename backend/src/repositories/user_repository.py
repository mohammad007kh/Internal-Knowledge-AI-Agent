"""Repository for User data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data-access layer for the ``users`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup, excludes soft-deleted rows."""
        stmt = (
            select(User)
            .where(func.lower(User.email) == email.lower())
            .where(User.deleted_at.is_(None))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(
        self, limit: int = 100, offset: int = 0
    ) -> Sequence[User]:
        """Return only active, non-deleted users."""
        stmt = (
            select(User)
            .where(User.is_active.is_(True))
            .where(User.deleted_at.is_(None))
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def set_active(self, id_: uuid.UUID, is_active: bool) -> User | None:
        """Toggle ``is_active`` for a user."""
        stmt = (
            update(User)
            .where(User.id == id_)
            .values(is_active=is_active)
            .returning(User)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_active(self) -> int:
        """Return the number of active, non-deleted users."""
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True))
            .where(User.deleted_at.is_(None))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
