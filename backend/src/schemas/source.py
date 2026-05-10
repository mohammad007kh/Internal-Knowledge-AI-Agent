"""Pydantic v2 schemas for Source endpoints (T-043).

FR-020: ``config_encrypted`` MUST NOT appear in any API response schema.
Every endpoint handler MUST call ``SourceResponse.model_validate(orm_obj)``
before returning — never expose raw ORM objects or ``config_encrypted``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.enums import SourceType
from src.schemas.sync_job import SyncJobResponse

# Canonical list of file extensions accepted by the consolidated "Files" source.
FileTypeLiteral = Literal["pdf", "docx", "xlsx", "csv", "txt", "markdown"]

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    """Request body for POST /sources."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable source name, unique per owner.",
    )
    source_type: SourceType = Field(
        ...,
        description="Connector type identifier.",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Connection configuration (credentials, URLs, etc.). "
            "Encrypted at rest; never returned in responses."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_no_slash(cls, v: str) -> str:
        """Source names must not contain '/' (used as path separator)."""
        if "/" in v:
            raise ValueError("Source name must not contain '/'.")
        return v


# ---------------------------------------------------------------------------
# Phase-2 structured request (T-004)
# ---------------------------------------------------------------------------

_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        # Canonical SourceType enum values
        "database",
        "file_upload",
        "web_url",
        "confluence",
        "sharepoint",
        # Legacy per-extension shorthands (back-compat — file team consolidation)
        "pdf",
        "docx",
        "xlsx",
        "csv",
        "txt",
        "markdown",
    }
)
# Canonical list of database dialects accepted by the consolidated "Database"
# source.  The granular ``postgresql``/``mysql``/``mssql``/``mongodb`` strings
# are NOT valid SourceType enum members and are rejected by Pydantic at INSERT
# time — they live here only as the ``db_type`` discriminator inside the
# connection payload.
DbTypeLiteral = Literal["postgresql", "mysql", "mssql", "mongodb"]
SQL_DB_TYPES: frozenset[str] = frozenset({"postgresql", "mysql", "mssql"})
# Includes both the canonical ``file_upload`` enum value and the legacy
# per-extension shorthands (kept for backward compatibility with older clients).
FILE_SOURCE_TYPES: frozenset[str] = frozenset(
    {"pdf", "docx", "xlsx", "csv", "txt", "markdown", "file_upload"}
)
_SYNC_MODES: frozenset[str] = frozenset({"manual", "scheduled", "delta"})
_RETRIEVAL_MODES: frozenset[str] = frozenset({"vector_only", "text_to_query", "hybrid"})


class DatabaseConnectionConfig(BaseModel):
    """Typed connection config for the consolidated ``database`` source type.

    The wizard sends fields in a typed shape (no JSON blobs).  The backend
    translates them into the underlying connector config:
      * SQL  → ``{connection_string, query, ssl_mode?}`` for ``DatabaseConnector``
      * Mongo → ``{uri, database, collection}`` for ``MongoDBConnector``

    For SQL dialects the ``query`` field is REQUIRED — the user must supply a
    SELECT statement that returns the rows to index. Read-only is enforced
    independently by ``is_safe_sql`` in the text_to_query node, which rejects
    any non-SELECT statement at execution time. The MongoDB ``collection``
    field is also required.

    Credentials are URL-quoted at translation time before being placed into
    any connection string (see :func:`SourceService._build_database_config`).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    db_type: DbTypeLiteral
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=255)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=4096)
    # SQL-only fields. ``query`` is required for SQL dialects.
    query: str | None = None
    ssl_mode: Literal["disable", "require"] | None = None
    # MongoDB-only field
    collection: str | None = None

    @model_validator(mode="after")
    def _enforce_per_dialect_shape(self) -> DatabaseConnectionConfig:
        """Enforce SQL vs MongoDB field requirements after parse.

        SQL dialects: ``query`` is required (must be a non-empty SELECT).
        MongoDB: ``collection`` is required.
        """
        if self.db_type == "mongodb":
            if not self.collection or not self.collection.strip():
                raise ValueError("'collection' is required for MongoDB sources.")
            return self
        # SQL branch
        if not self.query or not self.query.strip():
            raise ValueError("'query' is required for SQL dialects.")
        return self


class FileRef(BaseModel):
    """Reference to a single uploaded file inside the consolidated Files source.

    Each file lives in MinIO under ``object_key`` and carries enough metadata
    for the connector to download, type-check, and parse it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    object_key: str = Field(..., min_length=1, max_length=1024)
    original_name: str = Field(..., min_length=1, max_length=255)
    file_type: FileTypeLiteral
    size_bytes: int | None = Field(default=None, ge=0)


class SourceCreateRequest(BaseModel):
    """Structured request body for POST /sources (wizard flow).

    For file sources, prefer the ``files`` array (multi-file).  The legacy
    singular ``object_key`` field is retained for backward compatibility and
    accepted only when ``files`` is omitted.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # When ``auto_name_and_description`` is true the admin asked the AI to
    # write the name+description after ingestion; ``name`` may be empty on the
    # wire (we store ``"Untitled source"`` as a placeholder server-side). When
    # false, the user typed a name and the legacy validation applies.
    name: str = Field(default="", max_length=255)
    source_type: str
    connection: dict[str, Any] | None = None
    # Legacy single-file shape — kept for back-compat.
    object_key: str | None = None
    # New multi-file shape — preferred going forward.
    files: list[FileRef] | None = None
    description: str = ""
    sync_mode: str = "manual"
    sync_schedule: str | None = None
    retrieval_mode: str = "vector_only"
    citations_enabled: bool = True
    auto_name_and_description: bool = False

    @field_validator("name")
    @classmethod
    def _name_no_slash(cls, v: str) -> str:
        if "/" in v:
            raise ValueError("Source name must not contain '/'.")
        return v

    @model_validator(mode="after")
    def _require_name_unless_auto(self) -> SourceCreateRequest:
        """``name`` is required UNLESS the admin opted into AI auto-naming.

        Splitting this out of the field-level validator lets us cross-reference
        ``auto_name_and_description`` — Pydantic doesn't expose sibling fields
        inside ``@field_validator``.
        """
        if not self.auto_name_and_description and not self.name.strip():
            raise ValueError(
                "name is required (or set auto_name_and_description=true to "
                "have the assistant generate one after ingestion)."
            )
        return self

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, v: str) -> str:
        if v not in _SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type: {v}")
        return v

    @field_validator("sync_mode")
    @classmethod
    def _validate_sync_mode(cls, v: str) -> str:
        if v not in _SYNC_MODES:
            raise ValueError(f"Invalid sync_mode: {v}")
        return v

    @field_validator("retrieval_mode")
    @classmethod
    def _validate_retrieval_mode(cls, v: str) -> str:
        if v not in _RETRIEVAL_MODES:
            raise ValueError(f"Invalid retrieval_mode: {v}")
        return v

    @model_validator(mode="after")
    def _enforce_file_payload_shape(self) -> SourceCreateRequest:
        """Ensure file-typed sources include either ``files`` or ``object_key``.

        When ``files`` is provided it MUST be non-empty.  When both are
        provided, ``files`` wins and ``object_key`` is ignored.
        """
        if self.files is not None and len(self.files) == 0:
            raise ValueError("files must contain at least one entry when provided.")
        return self


class SourcePublicResponse(BaseModel):
    """Public source representation — never exposes connection_config or file_storage_path.

    ``is_active`` semantics: "approved/available to users". New sources default
    to ``False`` so admins must explicitly approve them after review.
    ``deleted_at IS None`` means the source is not soft-deleted; admin lists
    only return non-deleted rows.
    """

    id: str
    name: str
    source_type: str
    source_mode: str
    retrieval_mode: str
    description: str | None
    sync_mode: str
    sync_schedule: str | None
    last_synced_at: str | None
    status: str
    citations_enabled: bool
    is_active: bool = False
    deleted_at: datetime | None = None
    # AI auto-naming bookkeeping — surfaces "Naming…" placeholder in the UI
    # while pending and lets the admin distinguish AI-written from user-typed
    # values.
    name_status: str = "user_set"
    description_status: str = "user_set"
    auto_name_and_description: bool = False
    created_at: str
    updated_at: str


_SOURCE_MODES: frozenset[str] = frozenset({"snapshot", "live"})


class SourceUpdate(BaseModel):
    """Request body for PATCH /sources/{id} — all fields optional.

    Mirrors every editable field on the Source model so admin edits (Regenerate
    name+description, citation toggles, sync-mode changes) are persisted
    instead of silently dropped. Pydantic's default behavior of ignoring
    unknown fields is intentionally preserved — adding ``extra="forbid"`` would
    break older clients that send fields not listed here. To extend this
    schema, add the field below and forward it from
    :meth:`SourceService.update_source`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        None,
        min_length=1,
        max_length=255,
    )
    description: str | None = Field(
        None,
        max_length=2000,
        description="Free-text description shown in the admin UI and chat picker.",
    )
    citations_enabled: bool | None = None
    retrieval_mode: str | None = None
    sync_mode: str | None = None
    sync_schedule: str | None = Field(
        None,
        description="Cron string. Required when sync_mode='scheduled'.",
    )
    source_mode: str | None = None
    is_active: bool | None = None
    config: dict[str, Any] | None = Field(
        None,
        description="Full replacement of the connection config when provided.",
    )

    @field_validator("name")
    @classmethod
    def _name_no_slash(cls, v: str | None) -> str | None:
        """Source names must not contain '/' (matches SourceCreateRequest)."""
        if v is not None and "/" in v:
            raise ValueError("Source name must not contain '/'.")
        return v

    @field_validator("retrieval_mode")
    @classmethod
    def _validate_retrieval_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _RETRIEVAL_MODES:
            raise ValueError(f"Invalid retrieval_mode: {v}")
        return v

    @field_validator("sync_mode")
    @classmethod
    def _validate_sync_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _SYNC_MODES:
            raise ValueError(f"Invalid sync_mode: {v}")
        return v

    @field_validator("source_mode")
    @classmethod
    def _validate_source_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _SOURCE_MODES:
            raise ValueError(f"Invalid source_mode: {v}")
        return v

    @field_validator("sync_schedule")
    @classmethod
    def _validate_sync_schedule(cls, v: str | None) -> str | None:
        # Accept None (omitted) or a non-empty string. Full cron parsing is
        # deferred to the scheduler — this only catches blank-string drift
        # from the wire.
        if v is not None and not v.strip():
            raise ValueError("sync_schedule must not be blank when provided.")
        return v

    @model_validator(mode="after")
    def _require_schedule_when_scheduled(self) -> SourceUpdate:
        """Mirror the create-time invariant: scheduled sync needs a cron string.

        See ``api/v1/sources.py`` create handler — this enforces the same
        rule on the PATCH path so admins can't move a source into the
        ``scheduled`` mode without supplying a cron expression.
        """
        if self.sync_mode == "scheduled" and (
            self.sync_schedule is None or not self.sync_schedule.strip()
        ):
            raise ValueError(
                "sync_schedule (cron) required when sync_mode='scheduled'."
            )
        return self


# ---------------------------------------------------------------------------
# Response schemas — NO config_encrypted field intentionally (FR-020)
# ---------------------------------------------------------------------------


class SourceResponse(BaseModel):
    """Full source representation returned by the API.

    ``config_encrypted`` is deliberately absent (FR-020).

    Field semantics:
      * ``is_active`` — admin approval flag ("approved/available to users").
        Defaults to ``False`` for newly created rows; admin must explicitly
        flip it after review.
      * ``deleted_at`` — soft-delete marker. ``None`` means the source is
        active in the system (not soft-deleted).

    All wizard-collected fields are mirrored here so the frontend detail
    page can render the source without a second round-trip. Optional fields
    default to None / sensible defaults so older rows missing the columns
    (pre-T-004 schema) still validate.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    owner_id: uuid.UUID
    is_active: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Wizard-collected fields (T-004+)
    description: str | None = None
    source_mode: str = "snapshot"
    retrieval_mode: str = "vector_only"
    sync_mode: str = "manual"
    sync_schedule: str | None = None
    last_synced_at: datetime | None = None
    status: str = "pending"
    citations_enabled: bool = True


class SourceListItem(BaseModel):
    """Slim representation used inside paginated lists.

    ``is_active`` here means "approved/available to users". Soft-deleted rows
    (``deleted_at IS NOT NULL``) are filtered out by the listing endpoint and
    therefore never appear in this shape.

    Ingestion-clarity fields (``status``, ``last_synced_at``, ``description``,
    ``source_mode``, ``sync_mode``, ``document_count``, ``chunk_count``,
    ``has_upload``) power the four-stage admin sources strip
    (Uploaded / Parsed / Chunked / Approved). They mirror what
    :class:`SourceResponse` already exposes so the table can render without
    a per-row round-trip.

    ``has_upload`` is derived server-side from
    ``Source.file_storage_path IS NOT NULL`` — the path itself is never
    exposed (see :class:`Source` model docstring).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    is_active: bool
    deleted_at: datetime | None = None
    created_at: datetime
    latest_job: SyncJobResponse | None = None
    # Ingestion-clarity fields (T-107)
    status: str | None = None
    last_synced_at: datetime | None = None
    description: str | None = None
    source_mode: str | None = None
    sync_mode: str | None = None
    document_count: int = 0
    chunk_count: int = 0
    has_upload: bool = False


class PaginatedSources(BaseModel):
    """Envelope for paginated source lists."""

    items: list[SourceListItem]
    total: int
    limit: int
    offset: int


class TestConnectionResponse(BaseModel):
    """Result of POST /sources/{id}/test-connection."""

    success: bool
    message: str = ""


class DocumentResponse(BaseModel):
    """Slim document representation returned by GET /sources/{id}/documents.

    ``raw_storage_path`` is deliberately absent — it exposes internal MinIO
    object keys and must not leak via the API.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated envelope for document lists."""

    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class SourceStatsResponse(BaseModel):
    """Aggregate counts for GET /sources/{id}/stats."""

    document_count: int
    chunk_count: int
    last_synced_at: datetime | None = None
    sync_job_count: int
