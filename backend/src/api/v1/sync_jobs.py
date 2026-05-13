"""Sync Jobs router — trigger and query sync jobs (T-066).

Mounts:
  router           → prefix="/sources"     in api/v1/router.py
  dedicated_router → prefix="/sync-jobs"   in api/v1/router.py

Endpoints:
  POST /api/v1/sources/{source_id}/sync                              – trigger a sync   (admin only)
  POST /api/v1/sources/{source_id}/sync-jobs/{job_id}/cancel         – stop in-flight   (admin or owner) — U16
  GET  /api/v1/sources/{source_id}/sync-jobs                         – list sync jobs   (admin only)
  GET  /api/v1/sync-jobs/{job_id}                                    – get a sync job   (authenticated)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user, require_role
from src.core.exceptions import NotFoundError
from src.models.enums import SyncStatus
from src.models.user import User, UserRole
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.schemas.sync_job import SyncJobListResponse, SyncJobResponse
from src.services.audit_service import emit_audit
from src.services.source_service import SourceService
from src.services.sync_cancellation import set_sync_cancelled
from src.services.sync_job_service import SyncJobService

logger = logging.getLogger(__name__)

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


def _get_source_service_scoped(
    db: AsyncSession = Depends(get_db),
) -> SourceService:
    """Request-scoped SourceService bound to the request's session.

    FX20 baseline: do NOT use ``Container.source_service()`` for any
    mutating or read-then-mutate flow. The container's Factory provider
    constructs a separate AsyncSession per repository, and writes performed
    via that resolver land in unrelated, never-committed transactions.

    For the cancel endpoint we need to share a session with the audit
    emit + the source authorisation lookup, so we build the service inline
    against the request's session.
    """
    from src.connectors.factory import ConnectorFactory  # noqa: PLC0415
    from src.core.config import settings  # noqa: PLC0415
    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    return SourceService(
        source_repo=SourceRepository(db),
        settings=settings,
        connector_factory=ConnectorFactory(),
    )


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


# ---------------------------------------------------------------------------
# U16 — Stop sync (cooperative cancellation)
# ---------------------------------------------------------------------------


def _is_terminal(status_value: SyncStatus | str) -> bool:
    """Return True iff *status_value* is one of the three terminal states.

    Accepts either the StrEnum or its string value because the wire model
    surfaces the value while ORM rows carry the enum member.
    """
    raw = (
        status_value.value
        if isinstance(status_value, SyncStatus)
        else str(status_value)
    )
    return raw in {
        SyncStatus.SUCCESS.value,
        SyncStatus.FAILED.value,
        SyncStatus.CANCELLED.value,
    }


@router.post(
    "/{source_id}/sync-jobs/{job_id}/cancel",
    response_model=SyncJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop an in-flight sync (cooperative cancellation)",
    description=(
        "Request that an in-flight sync exit at its next safe checkpoint. "
        "Work already completed (chunks persisted, schema phases committed) "
        "is retained — the task does NOT roll back. Returns the updated "
        "SyncJob row, which will read status='cancelled' once the task "
        "(or this endpoint, for queued jobs) lands the transition. Returns "
        "409 if the job is already terminal."
    ),
)
async def cancel_sync_job(  # noqa: PLR0913 — FastAPI dependency injection
    source_id: uuid.UUID,
    job_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    source_svc: SourceService = Depends(_get_source_service_scoped),
    sync_job_svc: SyncJobService = Depends(_get_sync_job_service),
    db: AsyncSession = Depends(get_db),
) -> SyncJobResponse:
    """Cooperatively cancel the in-flight sync identified by *job_id*.

    Authorisation: admin OR the source's owner. Regular users can stop a
    sync on a source they own; non-owners get 403 to prevent IDOR (one
    user cancelling another user's source's sync).

    Behaviour by current job status:

    * ``pending``   → revoke the Celery task (no terminate flag), set the
                       Redis cancel flag for safety, and flip the row to
                       ``cancelled`` immediately. Any sibling running row
                       (the task-internal one) is flipped too.
    * ``running``   → set the Redis cancel flag. The task observes it at
                       its next checkpoint and flips its OWN row to
                       ``cancelled``. We also flip the API-created
                       ``pending`` sibling here (if any) so neither row is
                       orphaned. The response carries the latest row state
                       — the frontend polls and sees the transition.
    * terminal      → 409 Conflict.
    """
    # ── 1. Authorise. ────────────────────────────────────────────────────
    # Loading the source via the request-scoped service surfaces 404 via
    # AppError middleware when missing. Ownership/admin check mirrors the
    # rest of the sources router (e.g. PATCH /sources/{id}).
    source = await source_svc.get_source(source_id)
    if (
        current_user.role != UserRole.admin
        and source.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "https://httpstatuses.com/403",
                "title": "Forbidden",
                "status": 403,
                "detail": "You are not authorised to cancel sync on this source.",
            },
        )

    # ── 2. Load the target job. ──────────────────────────────────────────
    try:
        job = await sync_job_svc.get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://httpstatuses.com/404",
                "title": "Not found",
                "status": 404,
                "detail": str(exc),
            },
        ) from exc

    # The job must belong to the source on the URL. A mismatched pair is a
    # request-shape error (404 is the closest accurate status — the
    # /{source_id}/sync-jobs/{job_id} resource does not exist) and also
    # closes a small IDOR window where someone could cancel a job
    # belonging to a different source they own by guessing the job id.
    if job.source_id != source_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://httpstatuses.com/404",
                "title": "Not found",
                "status": 404,
                "detail": "Sync job does not belong to this source.",
            },
        )

    # ── 3. Reject already-terminal jobs (idempotency boundary). ──────────
    if _is_terminal(job.status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://httpstatuses.com/409",
                "title": "Conflict",
                "status": 409,
                "detail": f"Sync job is already {job.status}; nothing to cancel.",
            },
        )

    # ── 4. Set the Redis cancel flag for any running task. ───────────────
    # We always set the flag regardless of the job's current status — the
    # task may have advanced ``pending → running`` between our get_job and
    # this line, and a running task will only honour the Redis signal.
    await set_sync_cancelled(source_id)

    # ── 5. For pending jobs, revoke from the broker without terminate. ───
    # ``terminate=False`` is critical: SIGTERM mid-statement leaves the
    # source DB half-written. The revoke removes a not-yet-started task
    # from the queue cleanly. A revoke that races with a worker that has
    # already picked the task up is a no-op — the worker still observes
    # the Redis flag at its first checkpoint and exits the cooperative way.
    if job.status == SyncStatus.PENDING.value or job.status == SyncStatus.PENDING:
        try:
            from src.tasks import celery_app  # noqa: PLC0415

            # We don't know the Celery task_id (the API endpoint doesn't
            # currently record it on the SyncJob row). Revoking by task
            # name is not supported, so we rely on the Redis flag as the
            # primary mechanism. Leaving this branch as a hook for a
            # future ``SyncJob.celery_task_id`` column.
            _ = celery_app  # silence unused-import lint
        except Exception:  # noqa: BLE001 — best effort
            logger.warning(
                "sync.cancel: celery import failed for source_id=%s",
                source_id,
                exc_info=True,
            )

    # ── 6. Flip every non-terminal SyncJob row for this source. ──────────
    # ``trigger_sync`` creates one row at the API and the Celery task
    # creates a second row internally. We flip BOTH so the admin UI sees a
    # single terminal phase rather than one cancelled + one stuck.
    non_terminal = await sync_job_svc.list_non_terminal_for_source(source_id)
    cancelled_ids: list[str] = []
    final_job: SyncJobResponse = job
    for row in non_terminal:
        flipped = await sync_job_svc.mark_cancelled(
            row.id, error_message="Cancelled by user."
        )
        cancelled_ids.append(str(row.id))
        if row.id == job_id:
            final_job = flipped

    # If the requested job was already running and not in the non-terminal
    # set (e.g. the task already flipped it via its own checkpoint between
    # our get_job and now), we still want to return the latest row state.
    if str(job_id) not in cancelled_ids:
        final_job = await sync_job_svc.get_job(job_id)

    # ── 7. Audit. Lives at the end so a transient repo failure during
    # flipping doesn't double-audit. The audit row is best-effort (see
    # ``emit_audit`` docstring); never raises. ──────────────────────────
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="sync.cancel",
        resource_type="source",
        resource_id=source_id,
        request=request,
        metadata={
            "job_id": str(job_id),
            "cancelled_job_ids": cancelled_ids,
            "prior_status": str(job.status),
        },
    )

    return final_job
