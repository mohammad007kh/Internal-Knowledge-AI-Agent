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
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user, require_admin
from src.models.enums import SourceType
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


def _get_account_lockout():  # type: ignore[no-untyped-def]
    """Return the request-scoped :class:`AccountLockout` service.

    Sourced from the DI container so the credentials endpoint shares the
    same Redis-backed lockout state as ``AuthService.login``. Tests
    override this symbol via ``app.dependency_overrides`` to inject a mock.
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.account_lockout()


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
        # Match the study_source pattern: a broker outage must not 500 the
        # create call, but we want the failure on the record so an admin
        # can correlate "source created but never ingested".
        logger.warning(
            "sync_source enqueue failed for source_id=%s — proceeding",
            source.id,
            exc_info=True,
        )

    # Slice E1: kick off the studying-agent for DB sources so the U7 schema
    # viewer has a SchemaStudy to render. Best-effort — a Celery / broker
    # outage MUST NOT 500 the create endpoint. Schema studies are also
    # idempotent at the task level (see ``SchemaStudyRepository.is_running``)
    # so a duplicate enqueue is harmless.
    #
    # We dispatch via ``study_source.delay`` rather than the plain
    # ``send_task`` path so unit tests can monkeypatch ``.delay`` directly
    # on the task object (matching the slice-E1 contract).
    if source.source_type == SourceType.DATABASE:
        try:
            from src.tasks.study_source import study_source as _study  # noqa: PLC0415

            _study.delay(str(source.id))
        except ImportError:
            # Module-level import failure means the deployment is broken —
            # this is NOT a transient broker outage we want to swallow.
            logger.error(
                "study_source module failed to import — deployment broken",
                exc_info=True,
            )
            raise
        except Exception:  # noqa: BLE001
            logger.warning(
                "study_source enqueue failed for source_id=%s (broker?) — proceeding",
                source.id,
                exc_info=True,
            )

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

    from src.repositories.source_repository import SourceRepository  # noqa: PLC0415

    repo = SourceRepository(db)

    # Owner email — joined on Source.owner_id so the Overview footer can
    # render "Created … by alice@" without a second fetch (U10).
    response.owner_email = await repo.get_owner_email(source_id)

    # Project the latest SchemaStudy for DB sources. The latest study (any
    # state — drives ``study_state`` / ``tables_documented`` / ``last_error_*``)
    # and the latest *completed* study's one-line ``summary`` come back from a
    # single bounded ``schema_studies`` scan rather than two sequential reads
    # of the same table (U10 follow-up).
    if str(source.source_type) == "database" or getattr(
        source.source_type, "value", None
    ) == "database":
        latest_study, schema_summary = await repo.get_study_summary_bundle(source_id)
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

        # Studying-agent's one-line schema summary — from the latest
        # *completed* study's persisted SchemaDocument JSON (``summary`` key).
        # None when no study has completed, the JSON is None, or there is no
        # ``summary`` key (U10).
        if schema_summary is not None:
            response.schema_summary = schema_summary

    # FX35b: populate latest_job for the detail page. SourceResponse used to
    # omit this field; SourceListItem already had it on the list endpoint, so
    # frontend's SourceDetail (which extends SourceListItem) was getting None
    # on the detail page and derivePhase fell through to pending_upload.
    # Wrapped in try/except — a failed enrichment (Pydantic ValidationError on
    # a mock fixture, or a transient DB hiccup) must NOT 500 the detail
    # endpoint; the rest of the source row is still useful.
    try:
        from src.repositories.sync_job_repository import SyncJobRepository  # noqa: PLC0415

        sync_repo = SyncJobRepository()
        latest = await sync_repo.latest_for_source(db, source_id)
        if latest is not None:
            response.latest_job = SyncJobResponse.model_validate(latest)
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        logger.warning(
            "get_source: latest_job enrichment failed for source %s",
            source_id,
            exc_info=True,
        )

    return response


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
# Update DB credentials (U8 / FX4)
#
# A dedicated PATCH that:
#   * is admin/owner gated like every other source mutation,
#   * re-authenticates the caller via a "confirm_password" field (FX4),
#   * tests the *new* connection BEFORE persisting — a failure leaves the
#     source untouched so the modal can stay open with the connector error,
#   * on success: re-encrypts the merged config, resets connection_status to
#     "unknown" (the sync-status pill goes neutral until the next probe),
#     stamps connection_last_checked_at, clears connection_last_error, and
#     emits an audit row that NEVER includes the password.
# ---------------------------------------------------------------------------


class SourceCredentialsUpdateRequest(BaseModel):
    """Request body for ``PATCH /sources/{id}/credentials``.

    Mirrors the structured shape used at creation time
    (:class:`DatabaseConnectionConfig`) so the connector layer can be reused
    verbatim. All connection fields are optional — the route merges only
    the non-None values into the existing decrypted config so admins can
    rotate just the password without re-typing the host/port/db.

    ``confirm_password`` is the calling user's *own* password, used for
    re-authentication (FX4). The audit row records ``changed_fields`` but
    never the password value itself.

    ``connection_uri`` is an escape hatch for admins who prefer to paste a
    full URI (e.g. when the deployment fronts the DB behind a proxy with a
    non-standard URL shape). When provided, it overrides the structured
    fields and is persisted as-is into ``connection_string`` / ``uri``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Re-auth gate (required).
    confirm_password: str = Field(..., min_length=1, max_length=128)

    # Free-form override — when present, structured fields below are ignored
    # for connection-string assembly. Still passes through the connector
    # test before persistence. ``min_length=1`` rejects "" so an empty
    # string can't slot into the candidate config unvalidated.
    connection_uri: str | None = Field(default=None, min_length=1, max_length=4096)

    # Structured fields (optional; merged into the existing config). Every
    # string field carries ``min_length=1`` so an empty string ("") is
    # rejected at the schema layer rather than landing in the candidate
    # config and producing a malformed connection URL downstream.
    db_type: str | None = Field(default=None, min_length=1, max_length=32)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=4096)
    # SQL-only
    query: str | None = Field(default=None, min_length=1, max_length=8000)
    # ``ssl_mode`` is constrained to the set Postgres actually accepts.
    # ``DatabaseConnectionConfig`` only validates ssl_mode on the rebuild
    # branch (host/port/etc supplied), so without this Literal a stray
    # value sent on its own would slot into the candidate config
    # unvalidated. Match what postgres accepts for libpq's sslmode.
    ssl_mode: Literal["disable", "require", "verify-ca", "verify-full"] | None = (
        Field(default=None)
    )
    # MongoDB-only
    collection: str | None = Field(default=None, min_length=1, max_length=255)


@router.patch(
    "/{source_id}/credentials",
    response_model=SourceResponse,
    summary="Update DB connection credentials (re-auth + connector test required)",
)
async def update_source_credentials(  # noqa: PLR0913 — FastAPI deps
    source_id: uuid.UUID,
    payload: SourceCredentialsUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    account_lockout=Depends(_get_account_lockout),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    """Rotate/replace a database source's connection credentials.

    Flow (FX4 re-auth gate + lockout + Test-then-persist):

    1. Lockout check on the caller's email (matches AuthService.login). If
       the account is currently locked → 423; if Redis is required but
       down → 503. This MUST run before bcrypt so a leaked endpoint can't
       be turned into a CPU-burn or distributed-credential-stuffing vector.
    2. Verify the caller's confirm_password matches their hashed_password.
       Wrong password → record_failure on the lockout counter, then 401.
       Correct password → reset the lockout counter.
    3. Reject for non-database sources (only DB sources expose this verb).
    4. Delegate to :meth:`SourceService.update_database_credentials` which:
       * decrypts existing config + overlays submitted fields,
       * runs ``connector.test_connection`` against the candidate,
       * on success: re-encrypts + persists + resets connection health.
       Failure raises :class:`ConnectorTestFailedError` which the global
       error handler maps to 422 — modal stays open, NO persist.
    5. Emit ``source.credentials_change`` audit row with the list of
       changed field names — NEVER the password value (the audit_service's
       redactor strips ``password``-keyed entries defensively too).
    """
    # Step 1: lockout check (BEFORE bcrypt). Mirrors AuthService.login so
    # the per-email lockout state is shared across both gates.
    await account_lockout.check(current_user.email)

    # Step 2: re-auth. Wrong password → record_failure + 401.
    from src.services.password_service import PasswordService  # noqa: PLC0415

    if not PasswordService.verify_password(
        payload.confirm_password, current_user.hashed_password
    ):
        await account_lockout.record_failure(current_user.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "https://httpstatuses.com/401",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Confirm-password does not match.",
            },
        )

    # Successful re-auth — clear any prior failure counter for this email.
    await account_lockout.reset(current_user.email)

    # Step 3: ownership/admin gate + DB-only check.
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    if source.source_type != SourceType.DATABASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": "Credential editing is only available for database sources.",
            },
        )

    # Build the set of fields the caller actually wants to change. With the
    # FX7 dialog the frontend diffs the form against the fetched config and
    # sends ONLY the changed keys — so a save with no edits arrives here as
    # pure ``confirm_password`` with no rotation fields. That's a benign
    # no-op: we short-circuit with the source unchanged (no connector test,
    # no re-encrypt, no audit row, no re-study) rather than 400-ing the
    # admin who just clicked Save on an untouched form.
    submitted = payload.model_dump(exclude_unset=True)
    submitted.pop("confirm_password", None)
    if not submitted:
        return SourceResponse.model_validate(source)

    # Step 4: delegate to the service. Connector failure raises
    # ConnectorTestFailedError; we re-raise as HTTPException so the wire
    # body matches the rest of this router (FastAPI's 422 with our
    # problem-detail dict shape, modal-stays-open contract).
    from src.core.exceptions import ConnectorTestFailedError  # noqa: PLC0415

    try:
        updated, changed_fields = await service.update_database_credentials(
            source_id=source_id,
            submitted=submitted,
            connection_uri=payload.connection_uri,
        )
    except ConnectorTestFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "https://httpstatuses.com/422",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": exc.detail,
            },
        ) from exc
    except ValueError as exc:
        # Merged candidate failed DatabaseConnectionConfig validation.
        # ``str(exc)`` is the sanitised "fields: foo, bar" message — never
        # the candidate config itself.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "https://httpstatuses.com/422",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": str(exc),
            },
        ) from exc

    # Step 5: audit. The audit_service redacts any "password"-keyed entries
    # defensively, but we also pass only the field-NAME list — never the
    # value — so two layers of defence agree.
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.credentials_change",
        resource_type="source",
        resource_id=updated.id,
        request=request,
        metadata={"changed_fields": changed_fields},
    )
    await db.commit()

    # Slice E1: re-study the schema after a credential rotation so the U7
    # schema viewer reflects the new connection. Best-effort enqueue —
    # broker outage MUST NOT 500 the credential update. ImportError of
    # the task module is a deployment problem (NOT a transient broker
    # outage) so we surface it instead of swallowing.
    try:
        from src.tasks.study_source import study_source as _study  # noqa: PLC0415

        _study.delay(str(updated.id))
    except ImportError:
        logger.error(
            "study_source module failed to import — deployment broken",
            exc_info=True,
        )
        raise
    except Exception:  # noqa: BLE001
        logger.warning(
            "study_source enqueue failed for source_id=%s after credential "
            "rotation (broker?) — proceeding",
            updated.id,
            exc_info=True,
        )

    return SourceResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Read DB connection config — non-secret metadata only (FX7)
#
# Powers the EditCredentialsDialog pre-fill. SECURITY BOUNDARY:
#   * NEVER returns the password.
#   * NEVER returns the raw connection_string / uri / connection_uri (those
#     can embed the password).
#   * Returns ONLY the structured fields the admin already typed at creation
#     (db_type / host / port / database / username / ssl_mode / collection)
#     plus the SELECT `query` (which is not a secret) and a `has_password`
#     boolean so the UI can show "•••• (unchanged)" vs "(none set)".
#
# Enforcement is a strict response model (extra='forbid') + a deliberate
# field allowlist in the extraction helper below — a regression that adds a
# secret-bearing key fails both the model and the body-scanning test.
# ---------------------------------------------------------------------------


# Mongo/SQL connection-string drivername → db_type, for the legacy-config
# branch where the stored config has only a connection_string/uri.
_DRIVERNAME_TO_DB_TYPE: dict[str, str] = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mssql": "mssql",
    "mongodb": "mongodb",
}

# ssl_mode values the credentials schema accepts — anything else is dropped
# so the pre-fill never selects a value the form/backend would later reject.
_ALLOWED_SSL_MODES: frozenset[str] = frozenset(
    {"disable", "require", "verify-ca", "verify-full"}
)


class SourceConnectionConfigResponse(BaseModel):
    """Non-secret connection metadata for a database source (FX7).

    Strict (``extra='forbid'``) so a regression that tries to widen the
    response with ``password`` / ``connection_string`` / ``uri`` etc fails
    at the model layer — independently of the body-scanning test.
    """

    model_config = ConfigDict(extra="forbid")

    db_type: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    ssl_mode: str | None = None
    collection: str | None = None
    query: str | None = None
    has_password: bool = False


def _parse_connection_url(config: dict[str, Any]) -> Any | None:
    """Parse the connection-string-style key on *config*, if any.

    Returns the parsed :class:`sqlalchemy.engine.URL` or ``None`` when there
    is no such key or it doesn't parse. Used to (a) recover host/port/user
    for legacy configs that have nothing structured, and (b) detect whether
    a password is embedded in the URL (the ``has_password`` flag) without
    ever surfacing the URL itself.
    """
    raw_url = (
        config.get("connection_string")
        or config.get("uri")
        or config.get("connection_uri")
    )
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    try:
        return make_url(raw_url)
    except Exception:  # noqa: BLE001 — malformed URL: behave as "no URL".
        return None


def _extract_connection_config(
    config: dict[str, Any],
) -> SourceConnectionConfigResponse:
    """Project a decrypted connector config to the safe FX7 response shape.

    Pure (no crypto, no I/O beyond an in-memory URL parse). The response
    NEVER contains the password or the raw connection string/URI — a strict
    response model plus this deliberate allowlist are the enforcement.

    Two code paths:

    * **Structured config** — the modern shape written by
      :meth:`SourceService._build_database_config` carries ``host`` /
      ``port`` / ``database`` / ``username`` (SQL dialects) or ``database``
      / ``collection`` (Mongo), alongside a ``connection_string`` / ``uri``
      we deliberately ignore for the visible fields. We read the structured
      keys directly; any field still missing is back-filled from the parsed
      connection URL with its password component dropped. ``has_password``
      is ``True`` iff a non-empty ``password`` key is stored OR the parsed
      URL embeds one.
    * **Legacy config** — only a ``connection_string`` / ``uri`` /
      ``connection_uri`` key, no structured fields. We parse it with
      :func:`sqlalchemy.engine.make_url` and lift ``host`` / ``port`` /
      ``database`` / ``username`` from the parsed URL, **dropping the
      password component entirely**. ``db_type`` is mapped from the URL
      drivername when recognisable, else ``None``. ``has_password`` is
      ``bool(parsed.password)``.

    The ``query`` (SELECT statement) is included verbatim — for a DB source
    the query is not credential-bearing. ``ssl_mode`` is only surfaced when
    it is one of the values the credentials schema allows; a legacy URL's
    query-string ``sslmode`` is NOT trusted.
    """
    parsed = _parse_connection_url(config)
    url_has_password = bool(parsed.password) if parsed is not None else False
    db_type_from_url = (
        _DRIVERNAME_TO_DB_TYPE.get((parsed.get_backend_name() or "").lower())
        if parsed is not None
        else None
    )

    has_structured = any(
        k in config for k in ("host", "port", "database", "username")
    )

    if has_structured:
        # Structured fields win; back-fill the rest from the parsed URL
        # (password dropped). ssl_mode is read only from the structured key.
        ssl_raw = config.get("ssl_mode")
        ssl_mode = ssl_raw if ssl_raw in _ALLOWED_SSL_MODES else None
        host = _coerce_str(config.get("host")) or (
            _coerce_str(parsed.host) if parsed is not None else None
        )
        port = _coerce_port(config.get("port")) or (
            parsed.port if parsed is not None else None
        )
        username = _coerce_str(config.get("username")) or (
            _coerce_str(parsed.username) if parsed is not None else None
        )
        database = _coerce_str(config.get("database")) or (
            _coerce_str(parsed.database) if parsed is not None else None
        )
        return SourceConnectionConfigResponse(
            db_type=_coerce_db_type(config.get("db_type")) or db_type_from_url,
            host=host,
            port=port,
            database=database,
            username=username,
            ssl_mode=ssl_mode,
            collection=_coerce_str(config.get("collection")),
            query=_coerce_str(config.get("query")),
            has_password=bool(config.get("password")) or url_has_password,
        )

    # Legacy / structured-less: everything comes from the parsed URL.
    if parsed is None:
        return SourceConnectionConfigResponse(
            db_type=_coerce_db_type(config.get("db_type")),
            has_password=False,
        )
    return SourceConnectionConfigResponse(
        db_type=_coerce_db_type(config.get("db_type")) or db_type_from_url,
        host=_coerce_str(parsed.host),
        port=parsed.port,
        database=_coerce_str(parsed.database),
        username=_coerce_str(parsed.username),
        ssl_mode=None,  # never trust query-string sslmode from a legacy URL
        collection=_coerce_str(config.get("collection")),
        query=_coerce_str(config.get("query")),
        has_password=url_has_password,
    )


def _coerce_str(value: Any) -> str | None:
    """Return *value* as a non-empty string, else ``None``."""
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return None


def _coerce_port(value: Any) -> int | None:
    """Return *value* as a valid TCP port (1–65535), else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else None
    if isinstance(value, str) and value.strip().isdigit():
        port = int(value.strip())
        return port if 1 <= port <= 65535 else None
    return None


def _coerce_db_type(value: Any) -> str | None:
    """Normalise a stored ``db_type`` to the four values the UI knows."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"postgresql", "mysql", "mssql", "mongodb"}:
        return v
    # Tolerate drivername-style values ("postgresql+asyncpg") and "postgres".
    return _DRIVERNAME_TO_DB_TYPE.get(v.split("+", 1)[0])


@router.get(
    "/{source_id}/connection-config",
    response_model=SourceConnectionConfigResponse,
    summary="Non-secret connection metadata for a database source (pre-fill)",
)
async def get_source_connection_config(
    source_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
    db: AsyncSession = Depends(get_db),
) -> SourceConnectionConfigResponse:
    """Return the source's non-secret connection fields for the edit dialog.

    Authz + DB-only gating mirror ``PATCH /sources/{id}/credentials``: the
    caller must be the owner or an admin, and the source must be of type
    ``database`` (400 otherwise). 404 for a missing source.

    The decrypted config is read via :meth:`SourceService.get_source_config`
    (reusing the existing Fernet path — no crypto re-implemented here) and
    projected through :func:`_extract_connection_config`, which strips the
    password and the raw connection string/URI. Reading connection metadata
    is mildly sensitive, so we write an ``admin_audit_log`` row with
    ``action='source.connection_config_view'`` and an empty metadata dict
    (the trail records *that* the admin viewed the config, not its values).
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    if source.source_type != SourceType.DATABASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://httpstatuses.com/400",
                "title": "Bad Request",
                "status": 400,
                "detail": (
                    "Connection config is only available for database sources."
                ),
            },
        )

    from src.core.exceptions import NotFoundError as _NotFoundError  # noqa: PLC0415

    try:
        config = await service.get_source_config(source_id)
    except (HTTPException, _NotFoundError):
        # Let the global handlers map these (404 etc) — they carry no
        # connection-string material.
        raise
    except Exception as exc:  # noqa: BLE001
        # A decrypt/parse failure must NOT echo anything that could carry a
        # connection string. Log the type only; return a generic 500.
        logger.error(
            "Failed to read connection config for source_id=%s err_type=%s",
            source_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "https://httpstatuses.com/500",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Could not read the stored connection config.",
            },
        ) from None

    payload = _extract_connection_config(config)

    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.connection_config_view",
        resource_type="source",
        resource_id=source.id,
        request=request,
        metadata={},
    )
    await db.commit()

    # host / username are not secret, but they're operationally sensitive —
    # don't let a shared proxy / CDN cache this response.
    response.headers["Cache-Control"] = "no-store"
    return payload


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
