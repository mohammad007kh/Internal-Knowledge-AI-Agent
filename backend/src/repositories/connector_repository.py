"""Repository for Connector data access."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connector import Connector
from src.repositories.base_repository import BaseRepository


class ConnectorRepository(BaseRepository[Connector]):
    """Data-access layer for Connector entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Connector, session)

    async def get(self, connector_id: uuid.UUID) -> Connector | None:
        """Fetch a single Connector by PK."""
        return await self.get_by_id(connector_id)

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Connector]:
        """Return all connectors owned by *owner_id*."""
        stmt = (
            select(Connector)
            .where(Connector.owner_id == owner_id)
            .order_by(Connector.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, skip: int = 0, limit: int = 50) -> list[Connector]:
        """Return all connectors (admin view)."""
        stmt = (
            select(Connector)
            .order_by(Connector.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        """Count connectors owned by *owner_id*."""
        stmt = (
            select(func.count())
            .select_from(Connector)
            .where(Connector.owner_id == owner_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_all(self) -> int:
        """Count all connectors."""
        stmt = select(func.count()).select_from(Connector)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def delete(self, connector_id: uuid.UUID) -> bool:
        """Hard-delete a Connector by PK. Returns True if a row was removed."""
        return await self.hard_delete(connector_id)
