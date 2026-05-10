"""Sources router – CRUD + test-connection for Source entities (T-044).

All endpoints live under ``/api/v1/sources`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Admin users see all non-deleted sources (approved + pending); regular users
see only their own non-deleted sources. Pass ``available_only=true`` from
user-facing surfaces (chat session picker) to additionally restrict to
admin-approved (``is_active = TRUE``) rows. The ``config`` /
``config_encrypted`` field is never returned in any response.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
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
from src.services.db_introspection.schema_doc import SchemaDocument
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


def _get_source_service(
    db: AsyncSession = Depends(get_db),
) -> SourceService:
    """Construct :class:`SourceService` bound to the request-scoped DB session.

    Replaces the legacy ``Container.source_service()`` resolver, which built
    the inner ``SourceRepository`` against a *separate* :class:`AsyncSession`.
    That session was never committed by the route handler (the route only
    committed its own ``db``-scoped audit-log session), so every mutating
    call — ``create_source_v2``, ``update_source``, ``delete_source`` —
    flushed to a doomed session whose changes were rolled back at GC. From
    the API client's perspective the POST returned 200 with a UUID, but the
    row was gone seconds later (404 on the detail page).

    All repositories now share the same :class:`AsyncSession` as the audit
    log so the existing ``await db.commit()`` at the end of each mutation
    handler persists both the source mutation and the audit row in one
    transaction.

    Tests continue to override this symbol via
    ``app.dependency_overrides[_get_source_service] = ...`` to inject mocks —
    FastAPI ignores the dependency parameters when an override is active.
    """
    from src.connectors.factory import ConnectorFactory  # noqa: PLC0415
    from src.core.config import settings as _settings  # noqa: PLC0415
    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    return SourceService(
        source_repo=SourceRepository(session=db),
        settings=_settings,
        connector_factory=ConnectorFactory(),
    )


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


def _make_list_item(
    source: object,
    *,
    document_count: int = 0,
    chunk_count: int = 0,
    latest_study: object | None = None,
) -> SourceListItem:
    """Build a slim :class:`SourceListItem` for the admin sources table.

    Attaches the latest sync job (if any), the per-source aggregate counts
    that drive the four-stage ingestion-clarity strip
    (Uploaded / Parsed / Chunked / Approved), and the latest SchemaStudy's
    user-facing fields (``study_state``, partial-coverage counts, last error)
    so the DB-source verb column + DatabaseStudyStrip can render without
    a per-row round-trip.

    ``has_upload`` is derived server-side from
    ``Source.file_storage_path IS NOT NULL`` — the path itself is never
    leaked into the API response.

    ``latest_study`` is an optional :class:`SchemaStudy` ORM row (the most
    recent one for this source). When None the SchemaStudy-derived fields
    on the response stay null — non-DB sources, or DB sources whose
    studying agent has not yet run.
    """
    latest_raw = max(
        getattr(source, "sync_jobs", []),
        key=lambda j: j.created_at,
        default=None,
    )
    item = SourceListItem.model_validate(source)
    if latest_raw is not None:
        item.latest_job = SyncJobResponse.model_validate(latest_raw)
    item.document_count = document_count
    item.chunk_count = chunk_count
    item.has_upload = getattr(source, "file_storage_path", None) is not None

    if latest_study is not None:
        # Project the join — the studying agent's pipeline state, partial
        # flag, and most recent failure get surfaced inline so the admin
        # table can render the verb column without an N+1 fetch.
        # ``tables_documented`` is derived from the persisted SchemaDocument
        # JSON (the studying agent stores the full document there). Stays
        # None when the study hasn't completed yet — the UI tolerates that.
        item.study_state = getattr(latest_study, "state", None)
        item.last_error_phase = getattr(latest_study, "last_error_phase", None)
        item.last_error_message = getattr(latest_study, "last_error_message", None)
        doc_json = getattr(latest_study, "schema_document_json", None)
        if isinstance(doc_json, dict):
            tables = doc_json.get("tables")
            if isinstance(tables, list):
                item.tables_documented = len(tables)
        # tables_partial is the count of tables whose AI description failed
        # — not currently tracked at the document level. Leave None until
        # the studying agent stamps it explicitly.

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
        is_active=source.is_active,
        deleted_at=source.deleted_at,
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
        name_status=source.name_status,
        description_status=source.description_status,
        auto_name_and_description=source.auto_name_and_description,
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
    available_only: bool = Query(
        False,
        description=(
            "When true, restrict to admin-approved sources (is_active=true). "
            "Use this from user-facing surfaces such as the chat session "
            "source picker. The admin sources list omits this param so "
            "pending-approval rows remain visible."
        ),
    ),
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> PaginatedSources:
    """Return a paginated list of non-deleted sources.

    Admins receive all non-deleted sources (approved + pending). Regular
    users receive only their own non-deleted sources. Soft-deleted rows are
    always filtered out. Pass ``available_only=true`` to restrict to
    admin-approved sources (chat session picker behaviour).
    """
    if current_user.role == UserRole.admin:
        rows, total = await service.list_all_sources_with_counts(
            skip=offset, limit=limit, available_only=available_only
        )
    else:
        rows, total = await service.list_sources_for_owner_with_counts(
            owner_id=current_user.id,
            skip=offset,
            limit=limit,
            available_only=available_only,
        )
    return PaginatedSources(
        items=[
            _make_list_item(src, document_count=doc_n, chunk_count=chunk_n)
            for src, doc_n, chunk_n in rows
        ],
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
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    """Return the source if the caller is its owner or an admin.

    For DB sources the response also surfaces the latest SchemaStudy's
    pipeline state, partial-coverage counts, and most recent failure so
    the detail page's DatabaseStudyStrip + Verb-Column variants render
    without a second round-trip. The list endpoint deliberately omits
    these to avoid an N+1 fetch (it falls back to ``schema_status``).

    Raises 404 if the source does not exist, 403 if unauthorised.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)

    response = SourceResponse.model_validate(source)

    # Project the latest SchemaStudy for DB sources.
    if str(source.source_type) == "database" or getattr(
        source.source_type, "value", None
    ) == "database":
        latest_study = await _load_latest_schema_study(db, source_id)
        if latest_study is not None:
            response.study_state = getattr(latest_study, "state", None)
            response.last_error_phase = getattr(latest_study, "last_error_phase", None)
            response.last_error_message = getattr(
                latest_study, "last_error_message", None
            )
            doc_json = getattr(latest_study, "schema_document_json", None)
            if isinstance(doc_json, dict):
                tables = doc_json.get("tables")
                if isinstance(tables, list):
                    response.tables_documented = len(tables)

    return response


async def _load_latest_schema_study(
    db: AsyncSession, source_id: uuid.UUID
) -> object | None:
    """Return the most-recent :class:`SchemaStudy` row for *source_id*,
    or None when none exists.

    Used by :func:`get_source` to enrich the detail-page response. Lives
    here (rather than on a repository) because it's a single targeted
    read, not a CRUD-shaped operation.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from src.models.schema_study import SchemaStudy  # noqa: PLC0415

    stmt = (
        select(SchemaStudy)
        .where(SchemaStudy.source_id == source_id)
        .order_by(SchemaStudy.started_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


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
    """Soft-delete the source by setting ``deleted_at = now()``.

    The source record is retained for audit purposes; ``is_active`` is left
    unchanged so the historical approval state is preserved.
    Raises 404 if the source does not exist or is already soft-deleted.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    # Capture identifiers BEFORE deletion so the audit row keeps them after
    # the row is soft-deleted (deleted_at IS NOT NULL — but resource_id +
    # name are still valid history we want to log).
    captured_id = source.id
    captured_name = source.name
    # Soft-delete first; emit audit + commit together so the soft-delete
    # write and the audit row land in one transaction. (Previously the
    # commit ran BEFORE service.delete_source, so the soft-delete flush
    # was never persisted — the request returned 204 but the row stayed
    # visible.)
    await service.delete_source(source_id)
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.delete",
        resource_type="source",
        resource_id=captured_id,
        request=request,
        metadata={"name": captured_name},
    )
    await db.commit()
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
    request: Request,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResponse:
    """Attempt a live connection using the stored (decrypted) config.

    Always returns ``{"success": bool}`` — never raises 5xx for connectivity
    failures. Slice A: the probe result is also persisted on the Source row
    (``connection_status`` etc) and a single ``admin_audit_log`` row is
    emitted with ``action="source.connection_test"`` so admins can audit
    who tested what and when.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    ok = await service.test_connection(source_id)
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.connection_test",
        resource_type="source",
        resource_id=source_id,
        request=request,
        metadata={"success": ok},
    )
    await db.commit()
    return TestConnectionResponse(
        success=ok,
        message="" if ok else "Connection attempt failed — check credentials and network.",
    )


# ---------------------------------------------------------------------------
# Source sub-resources: documents + sync-runs
# ---------------------------------------------------------------------------


def _get_document_repo(  # type: ignore[no-untyped-def]
    db: AsyncSession = Depends(get_db),
):
    """Build a request-scoped :class:`DocumentRepository`.

    Switched away from ``Container.document_repo()`` because the container
    factory hands back a repo bound to a *new* session whose lifetime is
    tied to garbage collection — the connection-pool leak this slice fixes.
    """
    from src.repositories.document_repository import DocumentRepository  # noqa: PLC0415

    return DocumentRepository(db)


def _get_sync_job_repo():  # type: ignore[no-untyped-def]
    """Return a stateless :class:`SyncJobRepository`.

    The repo's methods accept the active :class:`AsyncSession` per call,
    so we can hand back a single instance not bound to any session.  This
    avoids the leak from ``Container.sync_job_repo()`` opening a fresh
    session that nothing closes.
    """
    from src.repositories.sync_job_repository import SyncJobRepository  # noqa: PLC0415

    return SyncJobRepository()


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
    db: AsyncSession = Depends(get_db),
) -> SourceStatsResponse:
    """Return document/chunk/sync-job counts + ``last_synced_at`` for a source.

    Admin-only.  Raises 404 when the source does not exist.
    """
    # Ensure the source exists (raises NotFoundError → 404 via error handler).
    await service.get_source(source_id)

    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    repo = SourceRepository(db)
    stats = await repo.get_stats(source_id)
    return SourceStatsResponse(**stats)


async def _propose_naming(
    source_id: uuid.UUID,
    *,
    service: SourceService,
    db: AsyncSession,
) -> dict[str, str]:
    """Profile the source and ask :class:`SourceNamingService` for a proposal.

    Shared by ``/auto-name`` (returns both fields) and the deprecated
    ``/refresh-description`` alias (returns the description only). Does
    NOT persist — F8 / F10 own the accept-and-save flow.
    """
    source = await service.get_source(source_id)

    from src.core.container import Container  # noqa: PLC0415

    factory = Container.source_profiler_factory()
    naming_service = Container.source_naming_service()

    profiler = factory.for_source(source)
    profile = await profiler.profile(source, db)
    naming = await naming_service.name_from_profile(profile)
    logger.info(
        "Generated AI naming proposal",
        extra={
            "source_id": str(source_id),
            "proposed_name_length": len(naming.name),
            "proposed_description_length": len(naming.description),
        },
    )
    return {
        "proposed_name": naming.name,
        "proposed_description": naming.description,
    }


@router.post(
    "/{source_id}/auto-name",
    summary="Generate an AI name + description proposal for a source (does not persist)",
)
async def auto_name(
    source_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Profile the source and propose a new ``name`` + ``description``.

    Admin-only. Returns ``{"proposed_name": ..., "proposed_description": ...}``.
    The caller is expected to PATCH the source if they want to persist —
    the audit trail (``source_description_history``) is appended on the
    accept side, NOT here.
    """
    return await _propose_naming(source_id, service=service, db=db)


@router.post(
    "/{source_id}/refresh-description",
    summary="Deprecated alias for /auto-name — returns description only",
    deprecated=True,
)
async def refresh_description(
    source_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Deprecated wrapper around ``/auto-name``.

    Kept for one release so existing UI callers (F10's regenerate button
    is mid-migration) don't break. Drops the ``proposed_name`` field so
    the response shape matches the legacy contract exactly.
    """
    proposal = await _propose_naming(source_id, service=service, db=db)
    return {"proposed_description": proposal["proposed_description"]}


# ---------------------------------------------------------------------------
# Description history (read-only audit trail)
# ---------------------------------------------------------------------------


class DescriptionHistoryItem(BaseModel):
    """One row of the description-replacement audit trail.

    ``description`` is the OLD value that was replaced — i.e. what the
    source displayed before the replacement landed. ``replaced_by_email``
    is joined from the ``users`` table for UI convenience and is ``None``
    when ``replaced_by`` is ``None`` (AI-driven replacement).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    description: str
    replaced_at: datetime
    replaced_by: UUID | None
    replaced_by_email: str | None


class PaginatedDescriptionHistory(BaseModel):
    """Paginated container for :class:`DescriptionHistoryItem` rows."""

    model_config = ConfigDict(extra="forbid")

    items: list[DescriptionHistoryItem]
    total: int
    limit: int
    offset: int


@router.get(
    "/{source_id}/description-history",
    response_model=PaginatedDescriptionHistory,
    summary="Paginated description-replacement audit trail",
)
async def list_description_history(
    source_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> PaginatedDescriptionHistory:
    """Return the source's description-replacement history (newest first).

    Admins see every source's history; regular users only see their own
    sources. Raises 404 if the source does not exist, 403 if the caller
    is neither an admin nor the source's owner.

    The endpoint reads from ``source_description_history`` and joins
    ``users`` so each row carries the replacing admin's email. Rows where
    ``replaced_by`` is ``NULL`` (AI auto-rename) surface
    ``replaced_by_email = None``.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)

    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    repo = SourceRepository(db)
    rows = await repo.list_description_history(source_id, limit=limit, offset=offset)
    total = await repo.count_description_history(source_id)
    return PaginatedDescriptionHistory(
        items=[DescriptionHistoryItem(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Schema document (U7 — admin DB schema viewer)
# ---------------------------------------------------------------------------


class SchemaDocumentResponse(BaseModel):
    """Wire envelope for ``GET /sources/{id}/schema-document``.

    Wraps the canonical :class:`SchemaDocument` (which is the studying
    agent's strict, validated model) with the few persistence-layer fields
    the admin viewer needs: which study produced this document, when, what
    pipeline state it terminated in, and a short fingerprint for
    glance-comparison across runs.

    The response intentionally does NOT include the source's connection
    config, decrypted credentials, or any other secret material — the
    studying agent persists a sanitised document that already has those
    fields stripped, and we re-validate via ``SchemaDocument.model_validate``
    on the way out so any tampered row is caught at the type boundary.
    """

    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    state: str
    started_at: datetime
    finished_at: datetime | None
    fingerprint_short: str = Field(
        ...,
        description="First 8 hex chars of the SchemaDocument fingerprint.",
        min_length=8,
        max_length=8,
    )
    schema_document: SchemaDocument


@router.get(
    "/{source_id}/schema-document",
    response_model=SchemaDocumentResponse,
    summary="Latest validated SchemaDocument for a DB source",
)
async def get_schema_document(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> SchemaDocumentResponse:
    """Return the latest completed :class:`SchemaDocument` for *source_id*.

    Admin or owner only — the source detail page mirrors the same auth
    rule as the description-history endpoint above. Returns 404 when:

    * the source itself does not exist (raised by ``SourceService.get_source``
      which the FastAPI error handler maps to a 404), or
    * no :class:`SchemaStudy` row exists with a non-null
      ``schema_document_json`` (i.e. the studying agent has not yet
      successfully completed a run).

    The persisted JSON is re-validated against the strict
    :class:`SchemaDocument` model so a hand-edited or otherwise corrupted
    row surfaces as a 500 with the standard sanitised-error envelope
    instead of leaking partial / wrong data.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)

    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    repo = SourceRepository(db)
    study = await repo.get_latest_completed_study(source_id)
    if study is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://httpstatuses.com/404",
                "title": "Not Found",
                "status": 404,
                "detail": "No completed schema study for this source.",
            },
        )

    # Strict validation — raises ValidationError if the persisted JSON
    # doesn't match SchemaDocument, which the global handler converts to
    # a sanitised 500. Surface it as a generic 500 so we don't echo the
    # exception text (which could leak DB internals).
    from pydantic import ValidationError  # noqa: PLC0415

    try:
        schema_document = SchemaDocument.model_validate(study.schema_document_json)
    except ValidationError as exc:
        logger.exception(
            "Persisted SchemaDocument failed strict validation for source_id=%s "
            "study_id=%s",
            source_id,
            getattr(study, "id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "https://httpstatuses.com/500",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Persisted schema document failed validation.",
            },
        ) from exc

    fingerprint = getattr(study, "fingerprint", None) or schema_document.fingerprint
    return SchemaDocumentResponse(
        study_id=study.id,
        state=str(study.state),
        started_at=study.started_at,
        finished_at=study.finished_at,
        fingerprint_short=fingerprint[:8],
        schema_document=schema_document,
    )


@router.post(
    "/{source_id}/schema-document/reveal-samples",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Audit-log emit for sample-values reveal in the admin viewer",
)
async def emit_samples_revealed(
    source_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Emit a ``source.schema.samples_revealed`` audit row.

    Admin-only. Called by the SchemaViewer when an admin flips the
    "Show sample values" toggle ON. We do NOT log when the toggle is
    flipped back to OFF — auditors only care about the moment of reveal.

    Returns 204 No Content. The audit row metadata is intentionally
    empty (``{}``) — the source identifier is on ``resource_id`` and the
    admin user is on ``admin_user_id``, which is everything the audit
    consumers need.
    """
    source = await service.get_source(source_id)
    # Admin-only via require_admin, but we still want a sane 404 path if
    # the source id doesn't exist — get_source raises NotFoundError → 404.
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.schema.samples_revealed",
        resource_type="source",
        resource_id=source.id,
        request=request,
        metadata={},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
