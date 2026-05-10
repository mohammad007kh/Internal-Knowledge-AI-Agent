"""Service layer for SyncJob lifecycle operations."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.enums import SyncStatus
from src.repositories.sync_job_repository import SyncJobRepository
from src.schemas.sync_job import SyncJobResponse


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
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.SUCCESS,
                finished_at=datetime.now(UTC),
                documents_synced=documents_synced,
                chunks_created=chunks_created,
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
            response = SyncJobResponse.model_validate(job)
            source_id_for_hook = job.source_id

        # Lifecycle hook: enqueue AFTER the session commits so we never
        # enqueue a Celery task pointing at a row whose transaction later
        # rolls back. The hook is best-effort — failures here never undo
        # the success transition above.
        await _maybe_enqueue_auto_name_for(source_id_for_hook)

        return response

    async def mark_failed(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
    ) -> SyncJobResponse:
        async with self._session() as session:
            job = await self._repo.update_status(
                session,
                job_id,
                status=SyncStatus.FAILED,
                finished_at=datetime.now(UTC),
                error_message=error_message,
            )
            if job is None:
                raise NotFoundError(f"SyncJob {job_id} not found.")
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
