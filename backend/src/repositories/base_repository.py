from __future__ import annotations
import uuid
from typing import Generic, TypeVar, Type, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import Base, SoftDeleteMixin

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    async def get_by_id(self, id_: uuid.UUID, include_deleted: bool = False) -> T | None:
        stmt = select(self._model).where(self._model.id == id_)
        if not include_deleted and issubclass(self._model, SoftDeleteMixin):
            stmt = stmt.where(self._model.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        stmt = select(self._model).limit(limit).offset(offset)
        if issubclass(self._model, SoftDeleteMixin):
            stmt = stmt.where(self._model.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(self, **kwargs) -> T:
        obj = self._model(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def update(self, id_: uuid.UUID, **kwargs) -> T | None:
        stmt = (
            update(self._model)
            .where(self._model.id == id_)
            .values(**kwargs)
            .returning(self._model)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, id_: uuid.UUID) -> bool:
        from datetime import datetime, timezone  # noqa: PLC0415
        obj = await self.get_by_id(id_)
        if obj and isinstance(obj, SoftDeleteMixin):
            obj.soft_delete()
            await self._session.flush()
            return True
        return False

    async def hard_delete(self, id_: uuid.UUID) -> bool:
        obj = await self.get_by_id(id_, include_deleted=True)
        if obj:
            await self._session.delete(obj)
            await self._session.flush()
            return True
        return False
