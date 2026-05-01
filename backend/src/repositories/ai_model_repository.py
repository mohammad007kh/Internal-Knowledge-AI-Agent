"""Repository for AIModel data access.

Encapsulates all SQL against the ``ai_models`` table.  Service layer never
touches raw queries — see :class:`~src.repositories.base_repository.BaseRepository`
for the conventions used across the codebase.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai_model import AIModel
from src.repositories.base_repository import BaseRepository


class AIModelRepository(BaseRepository[AIModel]):
    """Data-access layer for AIModel entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AIModel, session)

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    async def get_by_name(self, name: str) -> AIModel | None:
        stmt = select(AIModel).where(AIModel.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        q: str | None = None,
        provider: str | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AIModel], int]:
        """List AIModel rows with optional filters and a total count."""
        stmt = select(AIModel)
        count_stmt = select(func.count()).select_from(AIModel)

        if q:
            pattern = f"%{q.lower()}%"
            cond = func.lower(AIModel.name).like(pattern) | func.lower(
                AIModel.model_id
            ).like(pattern)
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        if provider:
            stmt = stmt.where(AIModel.provider == provider)
            count_stmt = count_stmt.where(AIModel.provider == provider)
        if active is not None:
            stmt = stmt.where(AIModel.is_active.is_(active))
            count_stmt = count_stmt.where(AIModel.is_active.is_(active))

        stmt = stmt.order_by(AIModel.created_at.desc()).limit(limit).offset(offset)

        rows = (await self._session.execute(stmt)).scalars().all()
        total = (await self._session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def find_duplicate(
        self,
        *,
        provider: str,
        base_url: str | None,
        model_id: str,
        deployment_name: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> AIModel | None:
        """Return an existing row with the same (provider, base_url, model_id, deployment) tuple."""
        stmt = select(AIModel).where(
            AIModel.provider == provider,
            AIModel.model_id == model_id,
        )
        if base_url is None:
            stmt = stmt.where(AIModel.base_url.is_(None))
        else:
            stmt = stmt.where(AIModel.base_url == base_url)
        if exclude_id is not None:
            stmt = stmt.where(AIModel.id != exclude_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        for row in rows:
            existing_dep = (row.extra_config or {}).get("deployment_name") or None
            if (existing_dep or None) == (deployment_name or None):
                return row
        return None

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    async def update_fields(
        self,
        ai_model_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> AIModel | None:
        """Apply *fields* in-place on the ORM object and return it."""
        existing = await self.get_by_id(ai_model_id)
        if existing is None:
            return None
        for k, v in fields.items():
            setattr(existing, k, v)
        await self._session.flush()
        await self._session.refresh(existing)
        return existing

    async def delete(self, ai_model_id: uuid.UUID) -> bool:
        return await self.hard_delete(ai_model_id)
