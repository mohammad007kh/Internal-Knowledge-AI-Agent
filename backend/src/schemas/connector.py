"""Pydantic v2 schemas for Connector endpoints.

FR-020 equivalent: config_encrypted MUST NOT appear in any API response schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.models.enums import SourceType


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ConnectorCreate(BaseModel):
    """Request body for POST /connectors."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    connector_type: SourceType
    config: dict[str, Any] | None = None


class ConnectorUpdate(BaseModel):
    """Request body for PUT /connectors/{id} — all fields optional."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = None
    is_active: bool | None = None
    config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Response schemas — NO config_encrypted field
# ---------------------------------------------------------------------------


class ConnectorResponse(BaseModel):
    """Full connector representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    connector_type: SourceType
    is_active: bool
    owner_id: uuid.UUID
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectorListResponse(BaseModel):
    """Paginated list envelope for connectors."""

    items: list[ConnectorResponse]
    total: int
