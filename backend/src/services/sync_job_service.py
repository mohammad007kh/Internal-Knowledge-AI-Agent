"""Service layer for SyncJob lifecycle operations."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.enums import SyncStatus
from src.repositories.sync_job_repository import SyncJobRepository
from src.schemas.sync_job import SyncJobResponse

logger = logging.getLogger(__name__)

# Mirrors the column type on Source.connection_last_error.
_CONNECTION_ERROR_TRUNC = 500
# Sentinel: how many consecutive failed sync runs flip the source to 'failed'.
_FAILED_RUN_THRESHOLD = 2


class SyncJobService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        sync_job_repo: SyncJobRepository,
    ) -> None:
        self._session_factory = session_factory
        self._repo = sync_job_repo

    @asynccontextmanager
    async def _session(self):  # type: ignore[return]
        async with self._session_factory() as session:
            async with session.begin():
                yield session

    async def create_job(self, source_id: uuid.UUID) -> SyncJobResponse:
        async with self._session() as session:
            job = await self._repo.create(session, source_id=source_id)
            return SyncJobResponse.model_validate(job)

    async def get_job(self, job_id: uuid.UUID) -> SyncJobResponse:
        async with self._session() as session:
            job = await self._repo.get(session, job_id)
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            return SyncJobResponse.model_validate(job)

    async def mark_running(self, job_id: uuid.UUID) -> SyncJobResponse:
        async with self._session() as session:
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            return SyncJobResponse.model_validate(job)

    async def mark_success(
        self,
        job_id: uuid.UUID,
        *,
        documents_synced: int,
        chunks_created: int,
    ) -> SyncJobResponse:
        async with self._session() as session:
            now = datetime.now(UTC)
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.SUCCESS,
                finished_at=now,
                documents_synced=documents_synced,
                chunks_created=chunks_created,
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            response = SyncJobResponse.model_validate(job)
            source_id_for_hook = job.source_id

            # Connection-health hook: a successful sync is irrefutable
            # proof we can reach the source — flip back to 'healthy' and
            # clear the last-error tooltip in the same transaction so the
            # admin UI doesn't render stale failure copy.
            await _set_connection_health(
                session,
                source_id=source_id_for_hook,
                status="healthy",
                error=None,
                checked_at=now,
            )

        # Lifecycle hook: enqueue AFTER the session commits so we never
        # enqueue a Celery task pointing at a row whose transaction later
        # rolls back. The hook is best-effort — failures here never undo
        # the success transition above.
        await _maybe_enqueue_auto_name_for(source_id_for_hook)

        return response

    async def mark_cancelled(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str | None = None,
    ) -> SyncJobResponse:
        """Flip *job_id* to ``status='cancelled'`` and stamp ``cancelled_at``.

        Idempotent on terminal rows — a second call for an already-terminal
        job is a no-op (returns the row as-is). The endpoint relies on this
        so a queued-job cancel followed by the task's own checkpoint-driven
        flip don't double-write.

        ``error_message`` is optional and defaults to a stable sentinel so
        the admin UI can render a uniform "Cancelled by admin" / "Cancelled
        at checkpoint" line without each call site reinventing the copy.
        """
        async with self._session() as session:
            current = await self._repo.get(session, job_id)
            if current is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            # No-op on terminal rows. Returning the existing row keeps the
            # endpoint contract simple (always returns *some* job row) and
            # makes the checkpoint flip safe even if the API endpoint
            # already marked the row cancelled.
            if current.status in {
                SyncStatus.SUCCESS,
                SyncStatus.FAILED,
                SyncStatus.CANCELLED,
            }:
                return SyncJobResponse.model_validate(current)

            now = datetime.now(UTC)
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.CANCELLED,
                cancelled_at=now,
                finished_at=now,
                error_message=error_message,
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            return SyncJobResponse.model_validate(job)

    async def list_non_terminal_for_source(
        self, source_id: uuid.UUID
    ) -> list[SyncJobResponse]:
        """Return every ``pending`` or ``running`` job for *source_id*.

        Used by the cancel endpoint: ``trigger_sync`` creates one row at the
        API layer and the Celery task creates a second row internally; on
        cancellation we need to flip BOTH (the API row is otherwise
        orphaned as ``pending`` forever and the task row is what the admin
        sees moving).
        """
        async with self._session() as session:
            jobs = await self._repo.list_non_terminal_by_source(
                session, source_id
            )
            return [SyncJobResponse.model_validate(j) for j in jobs]

    async def mark_failed(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
    ) -> SyncJobResponse:
        async with self._session() as session:
            now = datetime.now(UTC)
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.FAILED,
                finished_at=now,
                error_message=error_message,
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")

            # Auto-demote on N consecutive failures. We look at the *prior*
            # job status (LIMIT 2 ordered by created_at DESC: this row + the
            # one before it). If both rows are 'failed', flip the source to
            # 'failed'; otherwise mark 'degraded'. Only this source's runs
            # are inspected (the WHERE clause scopes by source_id) so a
            # different source's recent failure can't accidentally demote
            # an unrelated row.
            prior_failures = await _count_recent_failures(
                session,
                source_id=job.source_id,
                limit=_FAILED_RUN_THRESHOLD,
            )
            if prior_failures >= _FAILED_RUN_THRESHOLD:
                next_status = "failed"
            else:
                next_status = "degraded"
            truncated = (error_message or "")[:_CONNECTION_ERROR_TRUNC]
            await _set_connection_health(
                session,
                source_id=job.source_id,
                status=next_status,
                error=truncated,
                checked_at=now,
            )
            if next_status == "failed":
                logger.warning(
                    "source.auto_demoted: %d consecutive failures",
                    prior_failures,
                    extra={
                        "source_id": str(job.source_id),
                        "failed_run_count": prior_failures,
                    },
                )

            return SyncJobResponse.model_validate(job)

    async def list_for_source(
        self,
        source_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SyncJobResponse]:
        async with self._session() as session:
            jobs = await self._repo.list_by_source(
                session, source_id, limit=limit, offset=offset
            )
            return [SyncJobResponse.model_validate(j) for j in jobs]

    async def count_for_source(self, source_id: uuid.UUID) -> int:
        """Total sync-job count for *source_id*, ignoring pagination.

        Used by the list endpoint to populate the response's ``total`` so
        the admin sources detail page can render the correct
        "Showing X-Y of N" + Previous/Next pagination footer. Without this,
        the previous code passed ``len(jobs)`` (= page size at most),
        the footer's ``total > pageSize`` guard never tripped, and
        Previous/Next disappeared on sources with hundreds of runs.
        """
        async with self._session() as session:
            return await self._repo.count_by_source(session, source_id)

    async def get_latest_for_source(
        self, source_id: uuid.UUID
    ) -> SyncJobResponse | None:
        async with self._session() as session:
            job = await self._repo.latest_for_source(session, source_id)
            return SyncJobResponse.model_validate(job) if job else None


async def _set_connection_health(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    status: str,
    error: str | None,
    checked_at: datetime,
) -> None:
    """Update the connection-health columns on a Source row.

    Helper lives at module level so callers (sync hooks + the ``test_connection``
    service path) share one implementation. Caller owns the transaction —
    we only flush; commit is the surrounding ``async with self._session()``
    block's responsibility.
    """
    from src.models.source import Source  # noqa: PLC0415

    await session.execute(
        sa.update(Source)
        .where(Source.id == source_id)
        .values(
            connection_status=status,
            connection_last_error=error,
            connection_last_checked_at=checked_at,
        )
    )


async def _count_recent_failures(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    limit: int,
) -> int:
    """Count failed jobs among the *limit* most recent runs for *source_id*.

    Used by ``mark_failed`` to decide between ``degraded`` (a one-off blip)
    and ``failed`` (sustained inability to reach the source). The latest job
    has already been written to ``failed`` by the surrounding ``update_status``
    call, so a return value of ``limit`` means every one of the most recent
    *limit* runs failed — the auto-demote threshold.
    """
    from src.models.sync_job import SyncJob  # noqa: PLC0415

    stmt = (
        sa.select(SyncJob.status)
        .where(SyncJob.source_id == source_id)
        .order_by(SyncJob.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    statuses = [row[0] for row in result.all()]
    return sum(1 for s in statuses if s == SyncStatus.FAILED)


async def _maybe_enqueue_auto_name_for(source_id: uuid.UUID) -> None:
    """If *source_id* has ``name_status='pending_ai'``, enqueue the AI
    naming Celery task.

    Runs AFTER ``mark_success``'s session has exited (i.e., after the
    success transition has committed) so a rollback can't leave a Celery
    task pointing at a reverted row. Opens its own short-lived session
    for the status check.

    Errors are swallowed — auto-naming is best-effort and must never
    bubble back into ``mark_success``'s caller (the sync-source task).

    Lives at module level so the hook is mockable in tests via
    ``patch('src.services.sync_job_service._maybe_enqueue_auto_name_for')``
    without having to spin up a service instance.
    """
    import logging  # noqa: PLC0415 — local import keeps circular risk low

    from sqlalchemy import select  # noqa: PLC0415

    from src.core.database import AsyncSessionLocal  # noqa: PLC0415
    from src.models.source import Source  # noqa: PLC0415

    log = logging.getLogger(__name__)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Source.name_status).where(Source.id == source_id)
            )
            name_status = result.scalar_one_or_none()
        if name_status != "pending_ai":
            return

        from celery import current_app  # noqa: PLC0415

        current_app.send_task("tasks.auto_name_source", args=[str(source_id)])
        log.info(
            "auto_name_source enqueued",
            extra={"source_id": str(source_id), "trigger": "sync_success"},
        )
    except Exception:  # noqa: BLE001
        log.warning(
            "Failed to enqueue auto_name_source — sync success preserved",
            extra={"source_id": str(source_id)},
            exc_info=True,
        )
