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
            return SyncJobResponse.model_validate(job)

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

    async def get_latest_for_source(
        self, source_id: uuid.UUID
    ) -> SyncJobResponse | None:
        async with self._session() as session:
            job = await self._repo.latest_for_source(session, source_id)
            return SyncJobResponse.model_validate(job) if job else None
