"""Repository for Source data access. Implements T-041."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.chunk import Chunk
from src.models.document import Document
from src.models.source import Source
from src.models.sync_job import SyncJob
from src.repositories.base_repository import BaseRepository


class SourceRepository(BaseRepository[Source]):
    """Data-access layer for Source entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Source, session)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Source]:
        """Return all sources owned by the given user (active + inactive)."""
        stmt = (
            select(Source)
            .where(Source.owner_id == owner_id)
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Source]:
        """Return all active sources (admin view)."""
        stmt = (
            select(Source)
            .where(Source.is_active.is_(True))
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_owner_with_jobs(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Source]:
        """Return sources for *owner_id* with sync_jobs eagerly loaded."""
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        stmt = (
            select(Source)
            .options(selectinload(Source.sync_jobs))
            .where(Source.owner_id == owner_id)
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_with_jobs(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Source]:
        """Return all active sources with sync_jobs eagerly loaded."""
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        stmt = (
            select(Source)
            .options(selectinload(Source.sync_jobs))
            .where(Source.is_active.is_(True))
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        """Count sources owned by a user (for pagination totals)."""
        stmt = (
            select(func.count())
            .select_from(Source)
            .where(Source.owner_id == owner_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_active(self) -> int:
        """Count all active sources."""
        stmt = (
            select(func.count())
            .select_from(Source)
            .where(Source.is_active.is_(True))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def find_by_name_and_owner(
        self,
        name: str,
        owner_id: uuid.UUID,
    ) -> Source | None:
        """Look up a source by unique (name, owner_id) pair."""
        stmt = select(Source).where(
            Source.name == name,
            Source.owner_id == owner_id,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    async def deactivate(self, source_id: uuid.UUID) -> bool:
        """
        Soft-delete: sets is_active=False.

        Returns True if a row was updated, False if not found or already
        inactive.
        """
        stmt = (
            update(Source)
            .where(Source.id == source_id, Source.is_active.is_(True))
            .values(is_active=False)
            .returning(Source.id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    async def get_stats(self, source_id: uuid.UUID) -> dict[str, Any]:
        """Return aggregate counts + last sync timestamp for a source.

        Keys returned:
          * ``document_count``    — count of active documents
          * ``chunk_count``       — count of chunks (all, not filtered by is_active)
          * ``last_synced_at``    — Source.last_synced_at or None
          * ``sync_job_count``    — total historical sync runs

        Raises
        ------
        NotFoundError
            When no ``Source`` row exists for *source_id*.  Defense-in-depth
            against callers (e.g. Celery tasks) that bypass the router's own
            existence check and would otherwise see silent zeros.
        """
        src_result = await self._session.execute(
            select(Source).where(Source.id == source_id)
        )
        source = src_result.scalar_one_or_none()
        if not source:
            raise NotFoundError(f"Source {source_id} not found")

        doc_result = await self._session.execute(
            select(func.count())
            .select_from(Document)
            .where(
                Document.source_id == source_id,
                Document.is_active.is_(True),
            )
        )
        document_count = doc_result.scalar() or 0

        chunk_result = await self._session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.source_id == source_id)
        )
        chunk_count = chunk_result.scalar() or 0

        sync_result = await self._session.execute(
            select(func.count())
            .select_from(SyncJob)
            .where(SyncJob.source_id == source_id)
        )
        sync_job_count = sync_result.scalar() or 0

        return {
            "document_count": int(document_count),
            "chunk_count": int(chunk_count),
            "last_synced_at": source.last_synced_at if source else None,
            "sync_job_count": int(sync_job_count),
        }

    async def list_by_ids(self, source_ids: list[uuid.UUID]) -> list[Source]:
        """Bulk fetch by list of PKs; returns only active sources.

        Used by permission service to materialise permission lists (T-054).
        Returns an empty list immediately when *source_ids* is empty.
        """
        if not source_ids:
            return []
        stmt = (
            select(Source)
            .where(Source.id.in_(source_ids), Source.is_active.is_(True))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
