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
            ``True`` adds ``is_active = TRUE`` (chat picker / approved-only)
            AND excludes ``connection_status='failed'``. ``degraded`` is
            still surfaced — the contract is "lenient default": a one-off
            blip should not silently disappear from the picker, but a
            sustained outage (auto-demoted to ``failed``) should.
        """
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        doc_count = self._doc_count_subq().label("document_count")
        chunk_count = self._chunk_count_subq().label("chunk_count")

        base_filters = [Source.deleted_at.is_(None)]
        if owner_id is not None:
            base_filters.append(Source.owner_id == owner_id)
        if available_only:
            base_filters.append(Source.is_active.is_(True))
            base_filters.append(Source.connection_status != "failed")

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

    async def set_schema_status(
        self,
        source_id: uuid.UUID,
        status: str,
    ) -> None:
        """Stamp ``schema_status`` on a Source row (Slice E1).

        The studying-agent celery task calls this on every state transition
        so the admin sources list can render "studying / completed / failed"
        without joining ``schema_studies`` for every row. The caller owns
        the transaction — this method only emits the UPDATE.

        Accepts any string; the canonical vocabulary is enforced upstream
        by the model docstring (QUEUED | STUDYING | READY | STALE | FAILED
        plus the ``completed`` / ``failed`` aliases the task uses).

        On ``status == "completed"`` we additionally stamp
        ``last_studied_at = now()`` so the admin sources list can render
        "studied 4 min ago" without joining ``schema_studies``, and reset
        ``drift_signal_count = 0`` — a fresh study has just rebuilt the
        fingerprint and any prior drift was rolled into the new shape. We
        do NOT touch either of these on failure so admins still see the
        previous successful study time + drift count after a transient
        breakage.
        """
        values: dict[str, Any] = {"schema_status": status}
        if status == "completed":
            values["last_studied_at"] = func.now()
            # A re-study replaces the previous fingerprint outright; any
            # accumulated drift signals against the *old* fingerprint are
            # no longer meaningful.
            values["drift_signal_count"] = 0
        stmt = (
            update(Source)
            .where(Source.id == source_id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def update_connection_health(
        self,
        source_id: uuid.UUID,
        *,
        status: str,
        error: str | None,
        checked_at: Any,
    ) -> None:
        """Stamp the connection-health columns on a Source row (Slice A).

        The caller owns the transaction — we only emit the UPDATE; the
        surrounding session's commit is what makes it durable. Used by
        :meth:`SourceService.test_connection` after every probe so the UI
        can render "Last tested 4 min ago — succeeded/failed" without
        keeping client state.

        ``error`` MUST already be sanitized (no connection strings or
        credentials) and truncated to fit the 500-char column.
        """
        stmt = (
            update(Source)
            .where(Source.id == source_id)
            .values(
                connection_status=status,
                connection_last_error=error,
                connection_last_checked_at=checked_at,
            )
        )
        await self._session.execute(stmt)

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

    # ------------------------------------------------------------------ #
    # Description history (T-014 audit trail)
    # ------------------------------------------------------------------ #

    async def list_description_history(
        self,
        source_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return paginated description-history rows for *source_id*.

        Newest-first (FIFO from the audit trail's perspective: the most
        recently replaced description appears at the top of the list). Each
        row joins to ``users`` so callers can render "replaced by alice@"
        without a second round-trip; ``replaced_by_email`` is ``None`` when
        the replacement was performed by the AI auto-naming pipeline (which
        leaves ``replaced_by`` NULL).

        The query is hand-rolled so the JOIN stays a single LEFT JOIN — no
        relationship attribute is wired on the model and we don't need one
        for this read-only audit endpoint.
        """
        from src.models.source_description_history import (  # noqa: PLC0415
            SourceDescriptionHistory,
        )
        from src.models.user import User  # noqa: PLC0415

        stmt = (
            select(
                SourceDescriptionHistory.id,
                SourceDescriptionHistory.description,
                SourceDescriptionHistory.replaced_at,
                SourceDescriptionHistory.replaced_by,
                User.email.label("replaced_by_email"),
            )
            .select_from(SourceDescriptionHistory)
            .join(
                User,
                User.id == SourceDescriptionHistory.replaced_by,
                isouter=True,
            )
            .where(SourceDescriptionHistory.source_id == source_id)
            .order_by(SourceDescriptionHistory.replaced_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "id": row.id,
                "description": row.description,
                "replaced_at": row.replaced_at,
                "replaced_by": row.replaced_by,
                "replaced_by_email": row.replaced_by_email,
            }
            for row in result.all()
        ]

    async def count_description_history(self, source_id: uuid.UUID) -> int:
        """Return total description-history rows for *source_id* (for pagination)."""
        from src.models.source_description_history import (  # noqa: PLC0415
            SourceDescriptionHistory,
        )

        stmt = (
            select(func.count())
            .select_from(SourceDescriptionHistory)
            .where(SourceDescriptionHistory.source_id == source_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # ------------------------------------------------------------------ #
    # Schema studies (U7 — admin DB schema viewer)
    # ------------------------------------------------------------------ #

    async def get_latest_completed_study(
        self, source_id: uuid.UUID
    ) -> Any | None:
        """Return the newest :class:`SchemaStudy` for *source_id* with a
        non-null ``schema_document_json``, or None when no run has finished.

        Newest is determined by ``started_at`` (descending) — multiple studies
        may queue, but only the last one to actually persist a document is
        the canonical view for the admin schema-viewer endpoint.

        We deliberately filter on ``schema_document_json IS NOT NULL`` rather
        than ``state IN ('READY', 'READY_PARTIAL')`` so a future state name
        (e.g. ``READY_DEGRADED``) doesn't silently break this read.
        """
        from src.models.schema_study import SchemaStudy  # noqa: PLC0415

        stmt = (
            select(SchemaStudy)
            .where(
                SchemaStudy.source_id == source_id,
                SchemaStudy.schema_document_json.isnot(None),
            )
            .order_by(SchemaStudy.started_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # Bounded look-back for the detail-page bundle below — large enough that a
    # queued/running study in front of the last *completed* one doesn't hide
    # the summary, small enough to stay a single cheap LIMIT-ed scan.
    _STUDY_BUNDLE_SCAN_LIMIT = 5

    async def get_study_summary_bundle(
        self, source_id: uuid.UUID
    ) -> tuple[Any | None, str | None]:
        """Return ``(latest_study, schema_summary)`` for *source_id* in one query.

        Folds the detail endpoint's two former ``schema_studies`` reads —
        "latest study, any state" (drives ``study_state`` /
        ``tables_documented`` / ``last_error_*``) and "latest *completed*
        study's ``schema_document_json['summary']``" — into a single
        ``ORDER BY started_at DESC LIMIT n`` scan, picking both rows in
        Python:

        * ``latest_study`` — the most-recent :class:`SchemaStudy` row (any
          state), or ``None`` when the studying agent has never run. This is
          exactly the row the old ``_load_latest_schema_study`` returned.
        * ``schema_summary`` — the ``schema_document_json['summary']`` of the
          *newest* row whose ``schema_document_json`` is not null (the old
          ``get_latest_completed_study`` target), but only when that value is
          a non-empty string; ``None`` otherwise. Byte-identical to the
          previous two-call path: an older completed study's summary is never
          surfaced just because the newest completed one lacks the key.

        The scan window (:data:`_STUDY_BUNDLE_SCAN_LIMIT`) is intentionally
        small: in practice the latest completed study is at or near the top of
        the list, and a one-off cap keeps this O(1) regardless of how many
        studies have queued historically. If a deployment somehow had more
        than ``n`` newer non-completed studies in front of the last completed
        one, the summary line falls back to ``None`` — degraded, not wrong.
        """
        from src.models.schema_study import SchemaStudy  # noqa: PLC0415

        stmt = (
            select(SchemaStudy)
            .where(SchemaStudy.source_id == source_id)
            .order_by(SchemaStudy.started_at.desc())
            .limit(self._STUDY_BUNDLE_SCAN_LIMIT)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            return None, None

        latest_study = rows[0]
        schema_summary: str | None = None
        for row in rows:
            doc_json = getattr(row, "schema_document_json", None)
            if doc_json is None:
                continue
            # Newest row with a non-null document — mirror the old
            # get_latest_completed_study target. Read summary off *this* row
            # only, then stop (even if it has no usable summary).
            if isinstance(doc_json, dict):
                candidate = doc_json.get("summary")
                if isinstance(candidate, str) and candidate.strip():
                    schema_summary = candidate
            break
        return latest_study, schema_summary

    async def get_owner_email(self, source_id: uuid.UUID) -> str | None:
        """Return the email of the user who owns *source_id*, or None.

        Single targeted LEFT JOIN ``users`` ON ``sources.owner_id`` — the
        detail endpoint surfaces this so the Overview footer can render
        "Created … by alice@" without an extra round-trip. ``None`` when no
        Source row matches or its owner row is missing.
        """
        from src.models.user import User  # noqa: PLC0415

        stmt = (
            select(User.email)
            .select_from(Source)
            .join(User, User.id == Source.owner_id, isouter=True)
            .where(Source.id == source_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

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
