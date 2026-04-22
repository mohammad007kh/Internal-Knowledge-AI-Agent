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

    async def get_active(self) -> CompanyPolicy | None:
        """Return the most recently-created active policy row.

        The admin UI exposes a single-active-policy model — only the latest
        active row is surfaced.
        """
        stmt = (
            select(CompanyPolicy)
            .where(CompanyPolicy.is_active.is_(True))
            .order_by(CompanyPolicy.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_version(
        self, rule_text: str, created_by_user_id
    ) -> CompanyPolicy:
        """Deactivate all active policies, then insert a new active row."""
        from sqlalchemy import update as sa_update

        await self._session.execute(
            sa_update(CompanyPolicy)
            .where(CompanyPolicy.is_active.is_(True))
            .values(is_active=False)
        )
        obj = CompanyPolicy(
            rule_text=rule_text,
            is_active=True,
            created_by=created_by_user_id,
        )
        self._session.add(obj)
        await self._session.commit()
        await self._session.refresh(obj)
        return obj
