"""Repository for Embedder data access."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk import Chunk
from src.models.embedder import Embedder
from src.models.source import Source
from src.repositories.base_repository import BaseRepository


class EmbedderRepository(BaseRepository[Embedder]):
    """Data-access layer for Embedder entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Embedder, session)

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    async def get_by_name(self, name: str) -> Embedder | None:
        stmt = select(Embedder).where(Embedder.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self) -> Embedder | None:
        """Return the single active embedder, or ``None`` when unset."""
        stmt = select(Embedder).where(Embedder.is_active.is_(True))
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
    ) -> tuple[list[Embedder], int]:
        stmt = select(Embedder)
        count_stmt = select(func.count()).select_from(Embedder)

        if q:
            pattern = f"%{q.lower()}%"
            cond = func.lower(Embedder.name).like(pattern) | func.lower(
                Embedder.model_id
            ).like(pattern)
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        if provider:
            stmt = stmt.where(Embedder.provider == provider)
            count_stmt = count_stmt.where(Embedder.provider == provider)
        if active is not None:
            stmt = stmt.where(Embedder.is_active.is_(active))
            count_stmt = count_stmt.where(Embedder.is_active.is_(active))

        stmt = stmt.order_by(Embedder.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        total = (await self._session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def find_duplicate(
        self,
        *,
        provider: str,
        base_url: str | None,
        model_id: str,
        dimensions: int,
        exclude_id: uuid.UUID | None = None,
    ) -> Embedder | None:
        stmt = select(Embedder).where(
            Embedder.provider == provider,
            Embedder.model_id == model_id,
            Embedder.dimensions == dimensions,
        )
        if base_url is None:
            stmt = stmt.where(Embedder.base_url.is_(None))
        else:
            stmt = stmt.where(Embedder.base_url == base_url)
        if exclude_id is not None:
            stmt = stmt.where(Embedder.id != exclude_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_sources_using(self, embedder_id: uuid.UUID) -> int:
        stmt = select(func.count(Source.id)).where(Source.embedder_id == embedder_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_chunks_using(self, embedder_id: uuid.UUID) -> int:
        stmt = select(func.count(Chunk.id)).where(Chunk.embedder_id == embedder_id)
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    async def update_fields(
        self,
        embedder_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> Embedder | None:
        existing = await self.get_by_id(embedder_id)
        if existing is None:
            return None
        for k, v in fields.items():
            setattr(existing, k, v)
        await self._session.flush()
        await self._session.refresh(existing)
        return existing

    async def delete(self, embedder_id: uuid.UUID) -> bool:
        return await self.hard_delete(embedder_id)
