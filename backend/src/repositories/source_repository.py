"""Repository for Source data access. Implements T-041.

Visibility semantics
--------------------
* ``deleted_at IS NULL`` means the row is not soft-deleted (i.e. "exists" for
  admin and user-facing queries alike). All "exists" filters use this.
* ``is_active = TRUE`` means "approved by an admin / available to non-admin
  users". Admin views show every non-deleted source regardless of approval;
  the chat session source picker and any other user-facing surface should
  pass ``available_only=True`` so unapproved sources stay hidden.
"""

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
        available_only: bool = False,
    ) -> list[Source]:
        """Return non-deleted sources owned by the given user.

        ``available_only=True`` additionally restricts to ``is_active = TRUE``
        (admin-approved). Default ``False`` so admin views see pending rows.
        """
        stmt = (
            select(Source)
            .where(
                Source.owner_id == owner_id,
                Source.deleted_at.is_(None),
            )
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
    ) -> list[Source]:
        """Return all non-deleted sources (admin view by default).

        ``available_only=True`` restricts to admin-approved
        (``is_active = TRUE``) — the chat session source picker uses this.
        """
        stmt = (
            select(Source)
            .where(Source.deleted_at.is_(None))
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_owner_with_jobs(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        available_only: bool = False,
    ) -> list[Source]:
        """Return non-deleted sources for *owner_id* with sync_jobs eagerly loaded."""
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        stmt = (
            select(Source)
            .options(selectinload(Source.sync_jobs))
            .where(
                Source.owner_id == owner_id,
                Source.deleted_at.is_(None),
            )
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_with_jobs(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
    ) -> list[Source]:
        """Return all non-deleted sources with sync_jobs eagerly loaded.

        ``available_only=True`` restricts to admin-approved sources.
        """
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        stmt = (
            select(Source)
            .options(selectinload(Source.sync_jobs))
            .where(Source.deleted_at.is_(None))
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ #
    # Aggregate listings (T-107 ingestion-clarity)
    # ------------------------------------------------------------------ #

    def _doc_count_subq(self):  # type: ignore[no-untyped-def]
        """Correlated scalar subquery: count of active Documents per source.

        Mirrors the per-id ``get_stats`` semantics (Documents filtered by
        ``is_active = TRUE``) so the list and detail views never disagree.
        """
        return (
            select(func.count(Document.id))
            .where(
                Document.source_id == Source.id,
                Document.is_active.is_(True),
            )
            .correlate(Source)
            .scalar_subquery()
        )

    def _chunk_count_subq(self):  # type: ignore[no-untyped-def]
        """Correlated scalar subquery: count of Chunks per source.

        Chunks are not filtered (Chunk has no ``is_active`` column and
        ``embedding`` is NOT NULL — every persisted Chunk is fully embedded).
        Matches ``get_stats`` semantics.
        """
        return (
            select(func.count(Chunk.id))
            .where(Chunk.source_id == Source.id)
            .correlate(Source)
            .scalar_subquery()
        )

    async def list_with_counts(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
    ) -> tuple[list[tuple[Source, int, int]], int]:
        """Return ``[(source, document_count, chunk_count), ...]`` + total.

        Loads every list-item field — including the per-source aggregate
        counts — in a single round-trip.  ``sync_jobs`` is eagerly loaded
        via ``selectinload`` so the ``latest_job`` projection still works
        without an N+1.

        ``owner_id``
            When provided, restrict to sources owned by that user (regular
            user view).  ``None`` = admin view (all non-deleted sources).
        ``available_only``
            ``True`` adds ``is_active = TRUE`` (chat picker / approved-only).
        """
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        doc_count = self._doc_count_subq().label("document_count")
        chunk_count = self._chunk_count_subq().label("chunk_count")

        base_filters = [Source.deleted_at.is_(None)]
        if owner_id is not None:
            base_filters.append(Source.owner_id == owner_id)
        if available_only:
            base_filters.append(Source.is_active.is_(True))

        stmt = (
            select(Source, doc_count, chunk_count)
            .options(selectinload(Source.sync_jobs))
            .where(*base_filters)
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows: list[tuple[Source, int, int]] = [
            (row[0], int(row[1] or 0), int(row[2] or 0))
            for row in result.all()
        ]

        count_stmt = (
            select(func.count())
            .select_from(Source)
            .where(*base_filters)
        )
        total_result = await self._session.execute(count_stmt)
        total = int(total_result.scalar_one())

        return rows, total

    async def count_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        available_only: bool = False,
    ) -> int:
        """Count non-deleted sources owned by a user (for pagination totals)."""
        stmt = (
            select(func.count())
            .select_from(Source)
            .where(
                Source.owner_id == owner_id,
                Source.deleted_at.is_(None),
            )
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_active(self, *, available_only: bool = False) -> int:
        """Count all non-deleted sources.

        ``available_only=True`` restricts to admin-approved sources.
        """
        stmt = (
            select(func.count())
            .select_from(Source)
            .where(Source.deleted_at.is_(None))
        )
        if available_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def find_by_name_and_owner(
        self,
        name: str,
        owner_id: uuid.UUID,
    ) -> Source | None:
        """Look up a non-deleted source by unique (name, owner_id) pair.

        Soft-deleted rows are ignored so users can re-use a name once the
        previous source has been deleted.
        """
        stmt = select(Source).where(
            Source.name == name,
            Source.owner_id == owner_id,
            Source.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    async def soft_delete(self, source_id: uuid.UUID) -> bool:
        """
        Soft-delete: sets ``deleted_at = now()``.

        Returns True if a row was updated, False if not found or already
        soft-deleted. Approval state (``is_active``) is intentionally NOT
        modified — historical approval is preserved on the audit trail.
        """
        stmt = (
            update(Source)
            .where(Source.id == source_id, Source.deleted_at.is_(None))
            .values(deleted_at=func.now())
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
        """Bulk fetch by list of PKs; returns only non-deleted, approved sources.

        Used by permission service to materialise permission lists (T-054).
        Filters both ``deleted_at IS NULL`` and ``is_active = TRUE`` because the
        permission service surfaces sources to non-admin users — only approved
        rows should be visible. Returns an empty list immediately when
        *source_ids* is empty.
        """
        if not source_ids:
            return []
        stmt = (
            select(Source)
            .where(
                Source.id.in_(source_ids),
                Source.deleted_at.is_(None),
                Source.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
