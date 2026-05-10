"""Repository for AdminAuditLog data access (append-only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.admin_audit_log import AdminAuditLog
from src.models.user import User


@dataclass(frozen=True)
class AuditLogFilters:
    """Filter set for the admin audit-log viewer endpoint.

    Frozen / immutable so callers can pass it through without worrying about
    mutation.  All fields are optional — an instance with every field ``None``
    matches every row.
    """

    action: str | None = None
    resource_type: str | None = None
    admin_user_id: uuid.UUID | None = None
    from_: datetime | None = None
    to: datetime | None = None
    search: str | None = None


class AdminAuditLogRepository:
    """Append-only repository for admin audit-log entries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        admin_user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None,
        ip_address: str | None,
        metadata: dict[str, Any] | None,
    ) -> AdminAuditLog:
        row = AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_resource(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[AdminAuditLog]:
        stmt = (
            select(AdminAuditLog)
            .where(
                AdminAuditLog.resource_type == resource_type,
                AdminAuditLog.resource_id == resource_id,
            )
            .order_by(desc(AdminAuditLog.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ #
    # Paginated viewer query (admin audit-log page)                      #
    # ------------------------------------------------------------------ #

    def _apply_filters(self, stmt, filters: AuditLogFilters):
        """Apply ``AuditLogFilters`` to a base SELECT.

        Pulled out so :meth:`list_paginated` and :meth:`count` agree on the
        predicate set — drift here would silently misreport totals.
        """
        if filters.action is not None:
            stmt = stmt.where(AdminAuditLog.action == filters.action)
        if filters.resource_type is not None:
            stmt = stmt.where(AdminAuditLog.resource_type == filters.resource_type)
        if filters.admin_user_id is not None:
            stmt = stmt.where(AdminAuditLog.admin_user_id == filters.admin_user_id)
        if filters.from_ is not None:
            stmt = stmt.where(AdminAuditLog.created_at >= filters.from_)
        if filters.to is not None:
            stmt = stmt.where(AdminAuditLog.created_at <= filters.to)
        if filters.search is not None and filters.search.strip() != "":
            needle = f"%{filters.search.strip()}%"
            # ILIKE on metadata::text — substring match across the whole
            # JSON blob.  Cast is required because JSONB has no built-in
            # case-insensitive substring operator.
            stmt = stmt.where(
                cast(AdminAuditLog.metadata_, String).ilike(needle)
            )
        return stmt

    async def list_paginated(
        self,
        filters: AuditLogFilters,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[AdminAuditLog, str | None]]:
        """Return ``(row, admin_email_or_None)`` tuples newest-first.

        Joins ``users`` so callers can render the actor email without a
        second round-trip per row.  Uses an outer join — system events
        (no admin_user_id) survive the join with ``email = None``.
        """
        stmt = (
            select(AdminAuditLog, User.email)
            .outerjoin(User, AdminAuditLog.admin_user_id == User.id)
            .order_by(desc(AdminAuditLog.created_at), desc(AdminAuditLog.id))
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_filters(stmt, filters)
        result = await self._session.execute(stmt)
        return [(row, email) for row, email in result.all()]

    async def count(self, filters: AuditLogFilters) -> int:
        """Total matching rows for the same filter set as :meth:`list_paginated`."""
        stmt = select(func.count()).select_from(AdminAuditLog)
        stmt = self._apply_filters(stmt, filters)
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)
