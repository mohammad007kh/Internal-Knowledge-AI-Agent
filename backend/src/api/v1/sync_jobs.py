"""Sync Jobs router — trigger and query sync jobs (T-066).

Mounts:
  router           → prefix="/sources"     in api/v1/router.py
  dedicated_router → prefix="/sync-jobs"   in api/v1/router.py

Endpoints:
  POST /api/v1/sources/{source_id}/sync         – trigger a sync   (admin only)
  GET  /api/v1/sources/{source_id}/sync-jobs    – list sync jobs   (admin only)
  GET  /api/v1/sync-jobs/{job_id}               – get a sync job   (authenticated)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from src.core.deps import get_current_user, require_role
from src.models.user import User, UserRole
from src.schemas.sync_job import SyncJobListResponse, SyncJobResponse
from src.services.source_service import SourceService
from src.services.sync_job_service import SyncJobService

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Mounted at /sources  — owns /{source_id}/sync and /{source_id}/sync-jobs
router = APIRouter()

# Mounted at /sync-jobs — owns /{job_id}
dedicated_router = APIRouter()

# ---------------------------------------------------------------------------
# DI helpers (lazy imports avoid circular dependency at module load time)
# ---------------------------------------------------------------------------


def _get_source_service() -> SourceService:
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_service()


def _get_sync_job_service() -> SyncJobService:
    from src.core.container import Container  # noqa: PLC0415

    return Container.sync_job_service()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{source_id}/sync",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a sync job for a source",
    description=(
        "Creates a SyncJob record and enqueues a Celery task to sync the source. "
        "Returns 202 Accepted with the new job's details. Requires admin role."
    ),
)
async def trigger_sync(
    source_id: uuid.UUID,
    _current_user: User = Depends(require_role(UserRole.admin)),
    source_svc: SourceService = Depends(_get_source_service),
    sync_job_svc: SyncJobService = Depends(_get_sync_job_service),
) -> SyncJobResponse:
    """Trigger a background sync for the given source.

    Validates that the source exists (raises 404 via middleware if not),
    creates a SyncJob record, then dispatches the Celery task.
    """
    # Guard — raises NotFoundError (→ 404 via AppError middleware) if absent
    await source_svc.get_source(source_id)

    job = await sync_job_svc.create_job(source_id=source_id)

    # Local import prevents circular dependency at module-load time
    from src.tasks.sync_source import sync_source  # noqa: PLC0415

    sync_source.delay(str(source_id))

    return job


@dedicated_router.get(
    "/{job_id}",
    response_model=SyncJobResponse,
    summary="Get a sync job by ID",
    description="Returns the sync job with the given ID. Requires authentication.",
)
async def get_sync_job(
    job_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    sync_job_svc: SyncJobService = Depends(_get_sync_job_service),
) -> SyncJobResponse:
    """Return a single SyncJob by its UUID.

    Raises 404 via AppError middleware if the job does not exist.
    """
    return await sync_job_svc.get_job(job_id)


@router.get(
    "/{source_id}/sync-jobs",
    response_model=SyncJobListResponse,
    summary="List sync jobs for a source",
    description=(
        "Returns a paginated list of sync jobs for the given source. "
        "Requires admin role."
    ),
)
async def list_sync_jobs(
    source_id: uuid.UUID,
    offset: int = 0,
    limit: int = 20,
    _current_user: User = Depends(require_role(UserRole.admin)),
    source_svc: SourceService = Depends(_get_source_service),
    sync_job_svc: SyncJobService = Depends(_get_sync_job_service),
) -> SyncJobListResponse:
    """List all sync jobs for a source, with pagination.

    Validates that the source exists first (raises 404 via middleware if not).
    """
    # Guard — raises NotFoundError (→ 404 via AppError middleware) if absent
    await source_svc.get_source(source_id)

    # Two queries: the page of rows + the total count for the response
    # envelope. Without the explicit count the frontend pagination footer's
    # ``total > pageSize`` guard never trips for sources with > pageSize
    # runs (it sees `total === pageSize` and silently hides Previous/Next).
    jobs = await sync_job_svc.list_for_source(source_id, limit=limit, offset=offset)
    total = await sync_job_svc.count_for_source(source_id)

    return SyncJobListResponse(
        items=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )
