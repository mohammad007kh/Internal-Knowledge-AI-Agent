"""CRUD helpers for the source_permissions table."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError  # noqa: F401  (re-exported for callers)
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.source_permission import SourcePermission


class SourcePermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_source_and_user(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> SourcePermission | None:
        stmt = select(SourcePermission).where(
            SourcePermission.source_id == source_id,
            SourcePermission.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_ids_for_source(self, source_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(SourcePermission.user_id).where(
            SourcePermission.source_id == source_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_source_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(SourcePermission.source_id).where(
            SourcePermission.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, source_id: uuid.UUID, user_id: uuid.UUID) -> SourcePermission:
        """Raises IntegrityError on duplicate; caller converts to 409."""
        perm = SourcePermission(source_id=source_id, user_id=user_id)
        self._session.add(perm)
        await self._session.flush()
        await self._session.refresh(perm)
        return perm

    async def delete(self, source_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Return True if a row was deleted, False if not found."""
        stmt = (
            delete(SourcePermission)
            .where(
                SourcePermission.source_id == source_id,
                SourcePermission.user_id == user_id,
            )
            .returning(SourcePermission.id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.fetchone() is not None
