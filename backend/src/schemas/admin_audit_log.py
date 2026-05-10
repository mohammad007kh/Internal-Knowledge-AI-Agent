"""Pydantic schemas for the admin audit-log read endpoint.

Read-only — no Create/Update bodies. The audit-log is append-only, written
by :func:`src.services.audit_service.emit_audit` from inside other admin
mutations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntryPublic(BaseModel):
    """One audit-log row as exposed by the admin viewer endpoint.

    The wire id is the BIGINT primary key (serialised as a string so JS
    doesn't truncate it), NOT a UUID.  ``user_agent`` is always ``None``
    today — the underlying ``admin_audit_log`` table has no user-agent
    column.  We expose the field for forward-compatibility; the response
    contract from the frontend's perspective stays stable when we add it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    admin_user_id: uuid.UUID | None = None
    admin_user_email: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None


class AuditLogPage(BaseModel):
    """Paginated response envelope for ``GET /api/v1/admin/audit-log``."""

    model_config = ConfigDict(extra="forbid")

    items: list[AuditLogEntryPublic]
    total: int
    page: int
    page_size: int
