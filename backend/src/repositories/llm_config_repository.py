"""Repository for LLMConfiguration data access."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.llm_configuration import LLMConfiguration


class LLMConfigRepository:
    """Data-access layer for LLMConfiguration entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[LLMConfiguration]:
        result = await self._session.execute(select(LLMConfiguration))
        return list(result.scalars().all())

    async def get_by_slot(self, slot_name: str) -> LLMConfiguration | None:
        result = await self._session.execute(
            select(LLMConfiguration).where(LLMConfiguration.slot_name == slot_name)
        )
        return result.scalar_one_or_none()

    async def upsert(self, slot_name: str, data: dict) -> LLMConfiguration:
        existing = await self.get_by_slot(slot_name)
        if existing is not None:
            for k, v in data.items():
                setattr(existing, k, v)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        obj = LLMConfiguration(slot_name=slot_name, **data)
        self._session.add(obj)
        await self._session.commit()
        await self._session.refresh(obj)
        return obj
