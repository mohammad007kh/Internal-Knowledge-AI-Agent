"""Repository for CompanyPolicy data access."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company_policy import CompanyPolicy
from src.repositories.base_repository import BaseRepository


class CompanyPolicyRepository(BaseRepository[CompanyPolicy]):
    """Data-access layer for CompanyPolicy entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CompanyPolicy, session)

    async def list_active(self) -> list[CompanyPolicy]:
        """Return all active policy rules (``is_active=True``)."""
        stmt = (
            select(CompanyPolicy)
            .where(CompanyPolicy.is_active.is_(True))
            .order_by(CompanyPolicy.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
