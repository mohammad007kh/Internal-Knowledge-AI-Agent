"""Repository for ``schema_studies`` rows produced by the DB studying agent.

The studying agent writes one :class:`~src.models.schema_study.SchemaStudy`
row per study run. This repository owns the small set of operations the
``tasks.study_source`` celery task and the schema-viewer endpoint need:

* :meth:`create_study` — start a new run in state ``QUEUED``.
* :meth:`mark_completed` — terminal success (READY / READY_PARTIAL).
* :meth:`mark_failed` — terminal failure with phase + sanitised message.
* :meth:`is_running` — concurrency guard so two enqueues for the same source
  don't both fire the LLM pipeline.

Concurrent execution
--------------------
``is_running`` answers the question "is there a study row for this source
that has *not* reached a terminal state?". Terminal states are READY,
READY_PARTIAL, and the *_FAILED states (see
:data:`~src.models.schema_study.STUDY_STATES`). Anything else is treated as
in-flight. Two duplicate enqueues thus produce exactly one LLM call — the
second worker observes ``is_running == True`` and short-circuits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.schema_study import SchemaStudy

# Postgres advisory locks are keyed on a signed 64-bit integer. UUIDs are 128
# bits, so we fold the high half into the low half with XOR and clamp into
# the bigint range. This keeps the key stable for a given source_id (so two
# workers landing within milliseconds map to the same lock) while staying
# inside Postgres's accepted ``BIGINT`` domain.
_BIGINT_MASK: int = (1 << 63) - 1


def _uuid_to_int64(source_id: uuid.UUID) -> int:
    """Stable hash UUID → signed-bigint-safe positive int.

    XOR-folds the 128-bit UUID into 64 bits then masks to the positive
    BIGINT range so the value is always representable as a Postgres
    ``BIGINT`` argument to ``pg_advisory_xact_lock(bigint)``.
    """
    full = source_id.int
    folded = (full >> 64) ^ (full & ((1 << 64) - 1))
    return folded & _BIGINT_MASK

# Terminal states: anything outside this set is considered "still running".
# Mirrors the canonical vocabulary in src/models/schema_study.py — kept here
# as a frozenset rather than re-imported so a future state addition surfaces
# as a deliberate edit in this file.
_TERMINAL_STATES: frozenset[str] = frozenset(
    {
        "READY",
        "READY_PARTIAL",
        "CONNECT_FAILED",
        "INVENTORY_FAILED",
        "COLUMNS_FAILED",
        "SAMPLING_FAILED",
        "DESCRIBING_FAILED",
        "INDEXING_FAILED",
    }
)


class SchemaStudyRepository:
    """Data-access helpers for :class:`SchemaStudy`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Concurrency guard
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def lock_for_source(
        self, source_id: uuid.UUID
    ) -> AsyncIterator[None]:
        """Acquire a Postgres advisory lock keyed on *source_id*.

        Wraps the gate-check + create-study sequence so two Celery workers
        landing within milliseconds for the same source serialise on this
        lock instead of both passing :meth:`is_running` and inserting two
        SchemaStudy rows.

        ``pg_advisory_xact_lock`` auto-releases when the surrounding
        transaction ends (commit OR rollback), so as long as the caller
        commits/rolls back the session no lock leak is possible — even on
        an exception path.

        The key is derived from :func:`_uuid_to_int64`, which folds the
        128-bit UUID into a deterministic signed-bigint-safe int. Two
        callers with the same ``source_id`` always derive the same key.
        """
        key = _uuid_to_int64(source_id)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": key}
        )
        yield

    async def is_running(self, source_id: uuid.UUID) -> bool:
        """Return True iff a non-terminal study row exists for *source_id*.

        A worker that arrives while another is already studying the same
        source observes ``is_running == True`` and short-circuits — see the
        module docstring for the contract.
        """
        stmt = (
            select(SchemaStudy.id)
            .where(SchemaStudy.source_id == source_id)
            .where(SchemaStudy.state.notin_(_TERMINAL_STATES))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    # ------------------------------------------------------------------ #
    # Lifecycle writes
    # ------------------------------------------------------------------ #

    async def create_study(
        self,
        *,
        source_id: uuid.UUID,
        agent_version: str,
        state: str = "QUEUED",
    ) -> SchemaStudy:
        """Insert a fresh study row for *source_id*.

        The caller's session owns the transaction — this method only flushes
        so the generated id is populated for downstream UPDATEs.
        """
        row = SchemaStudy(
            source_id=source_id,
            agent_version=agent_version,
            state=state,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_completed(
        self,
        study_id: uuid.UUID,
        *,
        schema_document_json: dict[str, Any],
        fingerprint: str | None,
        partial: bool = False,
    ) -> None:
        """Stamp a study row as READY (or READY_PARTIAL when *partial*).

        Persists the validated SchemaDocument JSON, the fingerprint, and
        ``finished_at = now()``. State follows the partial flag.
        """
        terminal_state = "READY_PARTIAL" if partial else "READY"
        stmt = (
            update(SchemaStudy)
            .where(SchemaStudy.id == study_id)
            .values(
                state=terminal_state,
                schema_document_json=schema_document_json,
                fingerprint=fingerprint,
                partial=partial,
                finished_at=datetime.now(tz=UTC),
            )
        )
        await self._session.execute(stmt)

    async def mark_failed(
        self,
        study_id: uuid.UUID,
        *,
        phase: str,
        message: str,
        failure_category: str | None = None,
        attempts_made: int | None = None,
    ) -> None:
        """Stamp a study row as ``<phase>_FAILED`` with a sanitised message.

        ``message`` MUST already be sanitised — connection strings or
        credentials should never reach this method.

        ``failure_category`` / ``attempts_made`` are set only for DB *connection*
        failures (surfaced by ``connect_with_retry``); they are paired — both
        provided or both ``None`` (non-connection failures and cancellations
        leave them NULL).
        """
        terminal_state = f"{phase}_FAILED"
        stmt = (
            update(SchemaStudy)
            .where(SchemaStudy.id == study_id)
            .values(
                state=terminal_state,
                last_error_phase=phase,
                last_error_message=message,
                failure_category=failure_category,
                attempts_made=attempts_made,
                finished_at=datetime.now(tz=UTC),
            )
        )
        await self._session.execute(stmt)
