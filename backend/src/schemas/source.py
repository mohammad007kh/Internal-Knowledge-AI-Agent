"""Pydantic v2 schemas for Source endpoints (T-042).

Every endpoint handler MUST call ``SourceResponse.model_validate(orm_obj)``
before returning — never expose raw ORM objects or ``config_encrypted``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import SourceType

# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    """Request body for POST /sources."""

    name: str = Field(..., min_length=1, max_length=255)
    source_type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    """Request body for PATCH /sources/{id} — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    is_active: bool | None = None
    config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class SourceResponse(BaseModel):
    """Public representation of a Source.

    ``config_encrypted`` is intentionally absent — callers must never receive
    raw credentials.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    owner_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    """Paginated list of sources."""

    items: list[SourceResponse]
    total: int
    limit: int
    offset: int
