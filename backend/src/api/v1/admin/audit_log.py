"""Admin Audit-Log read endpoint (``GET /api/v1/admin/audit-log``).

Read-only viewer surface — admin-only — paginated and filterable.  The
underlying ``admin_audit_log`` table is append-only and is written from
:func:`src.services.audit_service.emit_audit` inside every admin mutation
endpoint.  This module exposes a single GET that lets admins inspect
those rows without giving them direct DB access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_admin
from src.models.user import User
from src.repositories.admin_audit_log_repository import (
    AdminAuditLogRepository,
    AuditLogFilters,
)
from src.schemas.admin_audit_log import AuditLogEntryPublic, AuditLogPage

router = APIRouter()


_PAGE_SIZE_DEFAULT = 50
_PAGE_SIZE_MAX = 200


@router.get("", response_model=AuditLogPage)
async def list_audit_log(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=_PAGE_SIZE_DEFAULT,
        ge=1,
        le=_PAGE_SIZE_MAX,
    ),
    action: str | None = Query(default=None, max_length=64),
    resource_type: str | None = Query(default=None, max_length=64),
    admin_user_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    """Paginated, filtered audit-log feed.

    Validation:
      * ``from`` must be ``<=`` ``to`` (when both are supplied) — returns
        ``422`` otherwise so the client can render a useful inline error
        instead of an empty result set that looks like "no entries".

    Pagination is 1-based on the wire (``page=1`` → first page) and is
    translated to SQL ``OFFSET`` here.  ``page_size`` is capped at 200 to
    keep memory bounded; clients that need exhaustive history should
    paginate.
    """
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_range",
                "message": "`from` must be earlier than or equal to `to`.",
            },
        )

    filters = AuditLogFilters(
        action=action,
        resource_type=resource_type,
        admin_user_id=admin_user_id,
        from_=from_,
        to=to,
        search=search,
    )

    repo = AdminAuditLogRepository(db)
    # Wrap both reads in a single transaction so `total` and `rows` come
    # from the same MVCC snapshot.  Without this, an audit row appended
    # between the two awaits would make `total` and `len(rows)` inconsistent
    # and break the client-side pagination math.  The audit table is
    # append-only, so READ COMMITTED (the default) is enough — the count's
    # snapshot is taken at the start of the txn.
    async with db.begin():
        rows = await repo.list_paginated(
            filters,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = await repo.count(filters)

    items = [
        AuditLogEntryPublic(
            # BIGINT id → string on the wire (JS Number.MAX_SAFE_INTEGER
            # is only 2^53 — bigint surfaces would overflow once the table
            # grows past that).
            id=str(row.id),
            created_at=row.created_at,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            admin_user_id=row.admin_user_id,
            admin_user_email=email,
            metadata=row.metadata_ or {},
            ip_address=str(row.ip_address) if row.ip_address is not None else None,
            user_agent=None,
        )
        for row, email in rows
    ]

    return AuditLogPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
