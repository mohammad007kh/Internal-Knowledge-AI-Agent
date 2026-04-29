"""Sources router – CRUD + test-connection for Source entities (T-044).

All endpoints live under ``/api/v1/sources`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Admin users see all active sources; regular users see only their own.
The ``config`` / ``config_encrypted`` field is never returned in any response.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user, require_admin
from src.models.user import User, UserRole
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.schemas.source import (
    FILE_SOURCE_TYPES,
    DocumentListResponse,
    DocumentResponse,
    PaginatedSources,
    SourceCreate,
    SourceCreateRequest,
    SourceListItem,
    SourcePublicResponse,
    SourceResponse,
    SourceStatsResponse,
    SourceUpdate,
    TestConnectionResponse,
)
from src.schemas.sync_job import SyncJobListResponse, SyncJobResponse
from src.services.audit_service import emit_audit
from src.services.source_service import SourceService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Inline schemas for inspection + presigned upload endpoints
# ---------------------------------------------------------------------------


class SourceInspectRequest(BaseModel):
    """Body for POST /sources/inspect — preview a source before persisting."""

    source_type: str = Field(
        ...,
        description=(
            "Connector type identifier: web_url|file_upload|database|"
            "confluence|sharepoint or a file shorthand (pdf|docx|xlsx|csv|"
            "txt|markdown)."
        ),
    )
    connection: dict[str, Any] = Field(default_factory=dict)


class SourceInspectResponse(BaseModel):
    """Result of POST /sources/inspect."""

    description: str
    schema_summary: dict[str, Any]


_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/plain",
        "text/markdown",
    }
)


class UploadUrlRequest(BaseModel):
    """Body for POST /sources/upload-url — request a presigned PUT URL."""

    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1)


class UploadUrlResponse(BaseModel):
    """Result of POST /sources/upload-url."""

    upload_url: str
    object_key: str


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_source_service() -> SourceService:
    """Resolve :class:`SourceService` from the DI container.

    Uses a lazy import so that the module can be loaded without triggering
    the full container wiring (helpful for unit tests).
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_service()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _assert_ownership_or_admin(owner_id: uuid.UUID, user: User) -> None:
    """Raise 403 if *user* is neither the owner nor an admin."""
    if user.role != UserRole.admin and user.id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "https://httpstatuses.com/403",
                "title": "Forbidden",
                "status": 403,
                "detail": "You are not authorised to access this source.",
            },
        )


def _make_list_item(source: object) -> SourceListItem:
    """Build a slim SourceListItem, attaching the latest sync job when available."""
    latest_raw = max(
        getattr(source, "sync_jobs", []),
        key=lambda j: j.created_at,
        default=None,
    )
    item = SourceListItem.model_validate(source)
    if latest_raw is not None:
        item.latest_job = SyncJobResponse.model_validate(latest_raw)
    return item


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SourcePublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new source",
    dependencies=[Depends(require_admin)],
)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> SourcePublicResponse:
    """Create a source from the wizard's structured request body.

    Admin-only. Connection config is Fernet-encrypted before persistence.
    File bytes never pass through this endpoint — use POST /sources/upload-url first.
    """
    is_file = body.source_type in FILE_SOURCE_TYPES

    if is_file and not body.files and not body.object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": (
                    "Provide either 'files' (preferred) or 'object_key' "
                    "for file source types."
                ),
            },
        )
    if not is_file and not body.connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": "connection required for non-file source types.",
            },
        )
    if body.sync_mode == "scheduled" and not body.sync_schedule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": "sync_schedule (cron) required when sync_mode='scheduled'.",
            },
        )

    from src.core.exceptions import ConflictError  # noqa: PLC0415

    try:
        source = await service.create_source_v2(body, owner_id=current_user.id)
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "https://httpstatuses.com/409",
                "title": "Conflict",
                "status": 409,
                "detail": str(exc),
            },
        ) from exc

    source_type_str = (
        source.source_type.value
        if hasattr(source.source_type, "value")
        else str(source.source_type)
    )
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.create",
        resource_type="source",
        resource_id=source.id,
        request=request,
        metadata={"name": source.name, "type": source_type_str},
    )
    await db.commit()

    # Kick off initial ingestion (best-effort — failures don't abort the response).
    try:
        from celery import current_app as _celery  # noqa: PLC0415

        _celery.send_task("tasks.sync_source", args=[str(source.id)])
    except Exception:  # noqa: BLE001
        pass

    return SourcePublicResponse(
        id=str(source.id),
        name=source.name,
        source_type=source_type_str,
        source_mode=source.source_mode,
        retrieval_mode=source.retrieval_mode,
        description=source.description,
        sync_mode=source.sync_mode,
        sync_schedule=source.sync_schedule,
        last_synced_at=source.last_synced_at.isoformat() if source.last_synced_at else None,
        status=source.status,
        citations_enabled=source.citations_enabled,
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Inspect a not-yet-persisted source (T-002)
# ---------------------------------------------------------------------------


@router.post(
    "/inspect",
    response_model=SourceInspectResponse,
    summary="Test connection + generate AI description (no persistence)",
)
async def inspect_source(
    body: SourceInspectRequest,
    _admin: User = Depends(require_admin),
) -> SourceInspectResponse:
    """Preview a source: test the connection, inspect schema, draft description.

    Admin-only.  Does not persist anything.  Never echoes the submitted
    ``connection`` dict back to the caller.
    """
    from src.core.container import Container  # noqa: PLC0415

    service = Container.source_inspection_service()
    try:
        result = await service.inspect_source(body.source_type, body.connection)
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "https://httpstatuses.com/422",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": str(exc),
            },
        ) from exc
    return SourceInspectResponse(**result)


# ---------------------------------------------------------------------------
# Presigned upload URL (T-003)
# ---------------------------------------------------------------------------


@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    summary="Generate a presigned PUT URL for direct-to-MinIO upload",
)
async def create_upload_url(
    body: UploadUrlRequest,
    _admin: User = Depends(require_admin),
) -> UploadUrlResponse:
    """Return a short-lived presigned PUT URL plus the generated object key.

    Admin-only.  The object key is namespaced by year/month plus a UUID so
    two users uploading the same filename do not collide.
    """
    if body.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": "Unsupported file type",
            },
        )

    from src.core.container import Container  # noqa: PLC0415

    storage = Container.storage_service()

    now = datetime.now(tz=timezone.utc)
    safe_name = body.filename.replace("/", "_").replace("\\", "_")
    object_key = f"uploads/{now.strftime('%Y/%m')}/{uuid4()}-{safe_name}"

    try:
        upload_url = await storage.generate_presigned_put_url(
            object_key=object_key,
            content_type=body.content_type,
            expires_minutes=15,
        )
    except Exception as exc:  # noqa: BLE001 - convert any MinIO failure to 503
        logger.exception(
            "Failed to generate presigned upload URL for object_key=%s",
            object_key,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "type": "https://httpstatuses.com/503",
                "title": "Service Unavailable",
                "status": 503,
                "detail": "Object storage is currently unavailable. "
                "Please try again shortly.",
            },
        ) from exc
    return UploadUrlResponse(upload_url=upload_url, object_key=object_key)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedSources,
    summary="List sources",
)
async def list_sources(
    offset: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> PaginatedSources:
    """Return a paginated list of sources.

    Admins receive all active sources; regular users receive only their own
    sources (both active and inactive).
    """
    if current_user.role == UserRole.admin:
        items, total = await service.list_all_active_sources(skip=offset, limit=limit)
    else:
        items, total = await service.list_sources_for_owner(
            owner_id=current_user.id, skip=offset, limit=limit
        )
    return PaginatedSources(
        items=[_make_list_item(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get a single source",
)
async def get_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> SourceResponse:
    """Return the source if the caller is its owner or an admin.

    Raises 404 if the source does not exist, 403 if unauthorised.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    return SourceResponse.model_validate(source)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Partially update a source",
)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    """Update only the provided fields.

    If ``config`` is included it is re-encrypted before persistence.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    updated = await service.update_source(source_id, payload)
    changed_fields = list(payload.model_dump(exclude_unset=True).keys())
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.update",
        resource_type="source",
        resource_id=updated.id,
        request=request,
        metadata={"changed_fields": changed_fields},
    )
    await db.commit()
    return SourceResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a source",
)
async def delete_source(
    source_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Set ``is_active = False``.

    The source record is retained for audit purposes.
    Raises 404 if the source does not exist.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    # Capture identifiers BEFORE deletion so the audit row keeps the resource_id.
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.delete",
        resource_type="source",
        resource_id=source.id,
        request=request,
        metadata={"name": source.name},
    )
    await db.commit()
    await service.delete_source(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@router.post(
    "/{source_id}/test-connection",
    response_model=TestConnectionResponse,
    summary="Test connector reachability",
)
async def test_connection(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> TestConnectionResponse:
    """Attempt a live connection using the stored (decrypted) config.

    Always returns ``{"success": bool}`` — never raises 5xx for connectivity
    failures.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    ok = await service.test_connection(source_id)
    return TestConnectionResponse(
        success=ok,
        message="" if ok else "Connection attempt failed — check credentials and network.",
    )


# ---------------------------------------------------------------------------
# Source sub-resources: documents + sync-runs
# ---------------------------------------------------------------------------


def _get_document_repo():  # type: ignore[no-untyped-def]
    """Resolve DocumentRepository from the DI container."""
    from src.core.container import Container  # noqa: PLC0415

    return Container.document_repo()


def _get_sync_job_repo():  # type: ignore[no-untyped-def]
    """Resolve SyncJobRepository from the DI container."""
    from src.core.container import Container  # noqa: PLC0415

    return Container.sync_job_repo()


@router.get(
    "/{source_id}/documents",
    response_model=DocumentListResponse,
    summary="List documents for a source",
)
async def list_source_documents(
    source_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    doc_repo=Depends(_get_document_repo),
) -> DocumentListResponse:
    """Return a paginated list of active documents belonging to *source_id*."""
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    docs = await doc_repo.list_by_source(source_id, offset=offset, limit=limit)
    total = await doc_repo.count_by_source(source_id)
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{source_id}/sync-runs",
    response_model=SyncJobListResponse,
    summary="List sync runs for a source",
)
async def list_source_sync_runs(
    source_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    sync_repo=Depends(_get_sync_job_repo),
    db: AsyncSession = Depends(get_db),
) -> SyncJobListResponse:
    """Return paginated sync job history for *source_id*."""
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    jobs = await sync_repo.list_by_source(db, source_id, limit=limit, offset=offset)
    total = await sync_repo.count_by_source(db, source_id)
    return SyncJobListResponse(
        items=[SyncJobResponse.model_validate(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Stats + refresh description (T-014)
# ---------------------------------------------------------------------------


@router.get(
    "/{source_id}/stats",
    response_model=SourceStatsResponse,
    summary="Aggregate counts + last-synced timestamp for a source",
)
async def get_source_stats(
    source_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    service: SourceService = Depends(_get_source_service),
) -> SourceStatsResponse:
    """Return document/chunk/sync-job counts + ``last_synced_at`` for a source.

    Admin-only.  Raises 404 when the source does not exist.
    """
    # Ensure the source exists (raises NotFoundError → 404 via error handler).
    await service.get_source(source_id)

    from src.core.container import Container  # noqa: PLC0415

    repo = Container.source_repo()
    stats = await repo.get_stats(source_id)
    return SourceStatsResponse(**stats)


@router.post(
    "/{source_id}/refresh-description",
    summary="Regenerate the AI description for a source (does not persist)",
)
async def refresh_description(
    source_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    service: SourceService = Depends(_get_source_service),
) -> dict[str, str]:
    """Regenerate (but don't save) a description for an existing source.

    Admin-only.  The caller is expected to PATCH the source with the
    ``proposed_description`` if they want to persist it.
    """
    source = await service.get_source(source_id)

    from src.core.container import Container  # noqa: PLC0415

    inspection_service = Container.source_inspection_service()
    proposed = await inspection_service.generate_description(source)
    return {"proposed_description": proposed}
