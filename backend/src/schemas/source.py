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
    # SQL-only fields
    query: str | None = None
    ssl_mode: Literal["disable", "require"] | None = None
    # MongoDB-only field
    collection: str | None = None

    @model_validator(mode="after")
    def _enforce_per_dialect_shape(self) -> DatabaseConnectionConfig:
        """Enforce SQL vs MongoDB field requirements after parse."""
        if self.db_type == "mongodb":
            if not self.collection or not self.collection.strip():
                raise ValueError("'collection' is required for MongoDB sources.")
        else:  # SQL dialects
            if not self.query or not self.query.strip():
                raise ValueError(
                    "'query' is required for SQL database sources."
                )
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

    name: str = Field(..., min_length=1, max_length=255)
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

    @field_validator("name")
    @classmethod
    def _name_no_slash(cls, v: str) -> str:
        if "/" in v:
            raise ValueError("Source name must not contain '/'.")
        return v

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
    """Public source representation — never exposes connection_config or file_storage_path."""

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
    created_at: str
    updated_at: str


class SourceUpdate(BaseModel):
    """Request body for PATCH /sources/{id} — all fields optional."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        None,
        min_length=1,
        max_length=255,
    )
    config: dict[str, Any] | None = Field(
        None,
        description="Full replacement of the connection config when provided.",
    )
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Response schemas — NO config_encrypted field intentionally (FR-020)
# ---------------------------------------------------------------------------


class SourceResponse(BaseModel):
    """Full source representation returned by the API.

    ``config_encrypted`` is deliberately absent (FR-020).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    owner_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceListItem(BaseModel):
    """Slim representation used inside paginated lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    is_active: bool
    created_at: datetime
    latest_job: SyncJobResponse | None = None


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
