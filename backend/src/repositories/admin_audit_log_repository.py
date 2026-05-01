"""Repository for AdminAuditLog data access (append-only)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.admin_audit_log import AdminAuditLog


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
