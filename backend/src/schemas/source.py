"""Pydantic v2 schemas for Source endpoints (T-043).

FR-020: ``config_encrypted`` MUST NOT appear in any API response schema.
Every endpoint handler MUST call ``SourceResponse.model_validate(orm_obj)``
before returning — never expose raw ORM objects or ``config_encrypted``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.enums import SourceType
from src.schemas.sync_job import SyncJobResponse

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
