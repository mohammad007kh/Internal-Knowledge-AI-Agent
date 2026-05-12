"""Repository for User data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.base_repository import BaseRepository

#: Status filter accepted by the admin user-list query.
UserStatusFilter = Literal["active", "inactive", "all"]


def _status_predicate(status: UserStatusFilter) -> ColumnElement[bool] | None:
    """Return the SQL predicate for *status*, or ``None`` for ``"all"``."""
    if status == "active":
        return User.is_active.is_(True)
    if status == "inactive":
        return User.is_active.is_(False)
    return None


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

    async def list_paginated(
        self,
        *,
        status: UserStatusFilter = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[User]:
        """Return non-deleted users for the admin list, ordered by creation.

        Unlike :meth:`list_active`, deactivated users ARE included by default
        (``status="all"``) so admins can see + re-activate them. Ordering is
        ``created_at`` ascending then ``id`` (a stable tiebreaker) so the slice
        returned for a given ``offset`` is deterministic across requests.
        """
        stmt = select(User).where(User.deleted_at.is_(None))
        predicate = _status_predicate(status)
        if predicate is not None:
            stmt = stmt.where(predicate)
        stmt = stmt.order_by(User.created_at.asc(), User.id.asc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_users(self, *, status: UserStatusFilter = "all") -> int:
        """Return the number of non-deleted users matching *status*."""
        stmt = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        predicate = _status_predicate(status)
        if predicate is not None:
            stmt = stmt.where(predicate)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def set_active(self, id_: uuid.UUID, is_active: bool) -> User | None:
        """Toggle ``is_active`` for a non-deleted user.

        Soft-deleted rows (``deleted_at IS NOT NULL``) are never matched, so a
        deleted account cannot be flipped back to active. Returns ``None`` when
        no live row matches *id_*.
        """
        stmt = (
            update(User)
            .where(User.id == id_)
            .where(User.deleted_at.is_(None))
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

    async def update_me(
        self,
        user_id: uuid.UUID,
        full_name: str | None = None,
        show_citations_preference: bool | None = None,
        new_password_hash: str | None = None,
    ) -> User:
        """Partial update of user profile fields and return the fresh row.

        Only non-``None`` arguments are applied. Commits so the change is
        visible to subsequent requests on fresh sessions.

        Raises:
            NoResultFound: The user no longer exists.
        """
        updates: dict[str, object] = {}
        if full_name is not None:
            updates["full_name"] = full_name
        if show_citations_preference is not None:
            updates["show_citations_preference"] = show_citations_preference
        if new_password_hash is not None:
            updates["hashed_password"] = new_password_hash

        if updates:
            await self._session.execute(
                update(User).where(User.id == user_id).values(**updates)
            )
            await self._session.commit()

        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one()
