"""Repository for SyncJob persistence operations."""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SyncStatus
from src.models.sync_job import SyncJob


class SyncJobRepository:
    def __init__(self, session: AsyncSession | None = None) -> None:
        # session param accepted for DI compatibility but methods take explicit sessions
        pass


    async def create(
        self,
        session: AsyncSession,
        *,
        source_id: uuid.UUID,
        status: SyncStatus = SyncStatus.PENDING,
    ) -> SyncJob:
        job = SyncJob(source_id=source_id, status=status)
        session.add(job)
        await session.flush()
        await session.refresh(job)
        return job

    async def get(self, session: AsyncSession, job_id: uuid.UUID) -> SyncJob | None:
        result = await session.execute(
            sa.select(SyncJob).where(SyncJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        *,
        status: SyncStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
        documents_synced: int | None = None,
        chunks_created: int | None = None,
    ) -> SyncJob | None:
        values: dict = {"status": status}
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        if error_message is not None:
            values["error_message"] = error_message
        if documents_synced is not None:
            values["documents_synced"] = documents_synced
        if chunks_created is not None:
            values["chunks_created"] = chunks_created
        await session.execute(
            sa.update(SyncJob).where(SyncJob.id == job_id).values(**values)
        )
        await session.flush()
        return await self.get(session, job_id)

    async def list_by_source(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SyncJob]:
        result = await session.execute(
            sa.select(SyncJob)
            .where(SyncJob.source_id == source_id)
            .order_by(SyncJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def latest_for_source(
        self, session: AsyncSession, source_id: uuid.UUID
    ) -> SyncJob | None:
        result = await session.execute(
            sa.select(SyncJob)
            .where(SyncJob.source_id == source_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_running(self, session: AsyncSession) -> list[SyncJob]:
        result = await session.execute(
            sa.select(SyncJob).where(SyncJob.status == SyncStatus.RUNNING)
        )
        return list(result.scalars().all())
