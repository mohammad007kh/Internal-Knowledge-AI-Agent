"""CRUD helpers for the source_permissions table."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select, union
from sqlalchemy.exc import IntegrityError  # noqa: F401  (re-exported for callers)
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.source import Source
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
        """Return every source the user can read.

        Two access paths union together:

        1. **Ownership** — the user created the source. Owner-implicit-access
           is the convention used elsewhere in the codebase (see
           SourceService.list_sources_for_owner_with_counts).  Without this
           branch, an admin/user who created a source had to ALSO be granted
           a row in source_permissions before retrieve_context would surface
           any chunks — which made every fresh source produce the synthesizer
           "I don't have enough information" boilerplate.  Confirmed root
           cause of the chat-returns-nothing incident on 2026-05-07.
        2. **Explicit grant** — a row in source_permissions (used when an
           admin grants access to another user).

        Soft-deleted sources are filtered out.  Approval state (is_active)
        is intentionally NOT checked here so admins can chat against their
        own pending sources during ingestion debugging; the
        ``available_only`` flag on the public sources list is what gates
        end-user visibility.
        """
        owned = select(Source.id).where(
            Source.owner_id == user_id,
            Source.deleted_at.is_(None),
        )
        granted = select(SourcePermission.source_id).where(
            SourcePermission.user_id == user_id
        )
        stmt = union(owned, granted)
        result = await self._session.execute(stmt)
        # union() returns rows of unlabeled UUIDs; .scalars().all() works.
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
