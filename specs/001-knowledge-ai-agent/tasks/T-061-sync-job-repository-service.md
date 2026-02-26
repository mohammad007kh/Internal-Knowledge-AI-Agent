# T-061 — SyncJob Repository, Service & Schemas

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
PostgreSQL 16 · UUID PKs
RFC 7807 Problem Details — all non-2xx API responses
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
```

## Goal
Implement `SyncJobRepository`, `SyncJobService`, and Pydantic schemas for sync jobs.
Wire all three into the DI container.

---

## Acceptance Criteria

- [ ] `SyncJobRepository` has `create`, `get`, `update_status`, `list_by_source`, `latest_for_source`, `list_running`
- [ ] `SyncJobService` raises `NotFoundException` for unknown job ids
- [ ] `SyncJobResponse` schema never exposes raw connection config
- [ ] `mark_running` sets `started_at = utcnow()`
- [ ] `mark_success` / `mark_failed` set `finished_at = utcnow()`
- [ ] containers.py wires `sync_job_repository` and `sync_job_service`

---

## 1  Repository — `app/repositories/sync_job_repository.py`

```python
# app/repositories/sync_job_repository.py
"""Repository for SyncJob persistence operations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SyncStatus
from app.models.sync_job import SyncJob
from app.repositories.base import BaseRepository


class SyncJobRepository(BaseRepository[SyncJob]):
    """CRUD + query operations for SyncJob."""

    model = SyncJob

    # ------------------------------------------------------------------ create
    async def create(
        self,
        session: AsyncSession,
        *,
        source_id: uuid.UUID,
        status: SyncStatus = SyncStatus.PENDING,
    ) -> SyncJob:
        """Insert a new SyncJob row and return it."""
        job = SyncJob(source_id=source_id, status=status)
        session.add(job)
        await session.flush()
        await session.refresh(job)
        return job

    # -------------------------------------------------------------------- get
    async def get(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
    ) -> SyncJob | None:
        result = await session.execute(
            sa.select(SyncJob).where(SyncJob.id == job_id)
        )
        return result.scalar_one_or_none()

    # ---------------------------------------------------------- update_status
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
        """Partial update — only provided kwargs are applied."""
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
            sa.update(SyncJob)
            .where(SyncJob.id == job_id)
            .values(**values)
        )
        await session.flush()
        return await self.get(session, job_id)

    # ------------------------------------------------------- list_by_source
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

    # ----------------------------------------------------- latest_for_source
    async def latest_for_source(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
    ) -> SyncJob | None:
        result = await session.execute(
            sa.select(SyncJob)
            .where(SyncJob.source_id == source_id)
            .order_by(SyncJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # --------------------------------------------------------- list_running
    async def list_running(self, session: AsyncSession) -> list[SyncJob]:
        """Return all jobs currently in RUNNING state (for crash-recovery)."""
        result = await session.execute(
            sa.select(SyncJob).where(SyncJob.status == SyncStatus.RUNNING)
        )
        return list(result.scalars().all())
```

---

## 2  Service — `app/services/sync_job_service.py`

```python
# app/services/sync_job_service.py
"""Business logic layer for SyncJob."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.exceptions import NotFoundException
from app.models.enums import SyncStatus
from app.models.sync_job import SyncJob
from app.repositories.sync_job_repository import SyncJobRepository
from app.schemas.sync_job import SyncJobResponse


class SyncJobService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        sync_job_repo: SyncJobRepository,
    ) -> None:
        self._sf = session_factory
        self._repo = sync_job_repo

    # ---------------------------------------------------------------- helpers
    def _now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    async def _get_or_raise(
        self, session, job_id: uuid.UUID
    ) -> SyncJob:
        job = await self._repo.get(session, job_id)
        if job is None:
            raise NotFoundException(f"SyncJob {job_id} not found")
        return job

    # --------------------------------------------------------------- create
    async def create_job(self, source_id: uuid.UUID) -> SyncJobResponse:
        async with self._sf() as session:
            async with session.begin():
                job = await self._repo.create(session, source_id=source_id)
            return SyncJobResponse.model_validate(job)

    # ------------------------------------------------------------------- get
    async def get_job(self, job_id: uuid.UUID) -> SyncJobResponse:
        async with self._sf() as session:
            job = await self._get_or_raise(session, job_id)
            return SyncJobResponse.model_validate(job)

    # --------------------------------------------------------- mark_running
    async def mark_running(self, job_id: uuid.UUID) -> None:
        async with self._sf() as session:
            async with session.begin():
                await self._get_or_raise(session, job_id)
                await self._repo.update_status(
                    session,
                    job_id,
                    status=SyncStatus.RUNNING,
                    started_at=self._now(),
                )

    # --------------------------------------------------------- mark_success
    async def mark_success(
        self,
        job_id: uuid.UUID,
        *,
        documents_synced: int,
        chunks_created: int,
    ) -> None:
        async with self._sf() as session:
            async with session.begin():
                await self._get_or_raise(session, job_id)
                await self._repo.update_status(
                    session,
                    job_id,
                    status=SyncStatus.SUCCESS,
                    finished_at=self._now(),
                    documents_synced=documents_synced,
                    chunks_created=chunks_created,
                )

    # ---------------------------------------------------------- mark_failed
    async def mark_failed(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
    ) -> None:
        async with self._sf() as session:
            async with session.begin():
                await self._get_or_raise(session, job_id)
                await self._repo.update_status(
                    session,
                    job_id,
                    status=SyncStatus.FAILED,
                    finished_at=self._now(),
                    error_message=error_message[:2000],  # DB TEXT but guard anyway
                )

    # ---------------------------------------------------- list_for_source
    async def list_for_source(
        self,
        source_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SyncJobResponse]:
        async with self._sf() as session:
            jobs = await self._repo.list_by_source(
                session, source_id, limit=limit, offset=offset
            )
            return [SyncJobResponse.model_validate(j) for j in jobs]

    # ------------------------------------------------- get_latest_for_source
    async def get_latest_for_source(
        self, source_id: uuid.UUID
    ) -> SyncJobResponse | None:
        async with self._sf() as session:
            job = await self._repo.latest_for_source(session, source_id)
            return SyncJobResponse.model_validate(job) if job else None
```

---

## 3  Pydantic Schemas — `app/schemas/sync_job.py`

```python
# app/schemas/sync_job.py
"""Pydantic schemas for SyncJob API surface."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import SyncStatus


class SyncJobResponse(BaseModel):
    """Read schema returned to callers."""
    model_config = ConfigDict(from_attributes=True)

    id:               uuid.UUID
    source_id:        uuid.UUID
    status:           SyncStatus
    started_at:       datetime | None
    finished_at:      datetime | None
    error_message:    str | None
    documents_synced: int
    chunks_created:   int
    created_at:       datetime
    updated_at:       datetime


# SyncJobCreate is internal-only (no user-controlled fields).
# The service hard-codes status=PENDING on creation.
```

---

## 4  DI Container — `app/containers.py` patch

```python
# Inside ApplicationContainer — add after SourcePermissionService providers:

    # ── SyncJob ─────────────────────────────────────────────────────────────
    sync_job_repository: providers.Factory[SyncJobRepository] = providers.Factory(
        SyncJobRepository
    )

    sync_job_service: providers.Factory[SyncJobService] = providers.Factory(
        SyncJobService,
        session_factory=db.provided.session_factory,
        sync_job_repo=sync_job_repository,
    )
```

Add corresponding imports at top of `containers.py`:

```python
from app.repositories.sync_job_repository import SyncJobRepository
from app.services.sync_job_service import SyncJobService
```

---

## 5  Verification Checklist

```bash
# Unit smoke (no DB required)
python -c "
from app.schemas.sync_job import SyncJobResponse
from app.models.enums import SyncStatus
assert SyncStatus.RUNNING.value == 'running'
print('schema OK')
"

# Integration — run with pytest
pytest tests/integration/test_sync_job_service.py -v
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-033 — job lifecycle | `mark_running`, `mark_success`, `mark_failed` |
| FR-033 — error capture | `error_message` stored, truncated to 2000 chars |
| FR-033 — latest job query | `get_latest_for_source` |
