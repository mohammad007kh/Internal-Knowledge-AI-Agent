"""CRUD repository for the Document ORM model."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import Document


class DocumentRepository:
    """
    All Document database access is encapsulated here.
    Service layer never touches raw SQL.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(self, document_id: uuid.UUID) -> Document | None:
        stmt = select(Document).where(
            Document.id == document_id,
            Document.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_source(
        self,
        source_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Document]:
        stmt = (
            select(Document)
            .where(
                Document.source_id == source_id,
                Document.is_active.is_(True),
            )
            .order_by(Document.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_by_source(self, source_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            Document.source_id == source_id,
            Document.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def bulk_create(self, documents: list[Document]) -> list[Document]:
        self._session.add_all(documents)
        await self._session.flush()
        return documents

    async def soft_delete(self, document_id: uuid.UUID) -> None:
        stmt = (
            update(Document)
            .where(Document.id == document_id)
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def soft_delete_by_source(self, source_id: uuid.UUID) -> int:
        stmt = (
            update(Document)
            .where(
                Document.source_id == source_id,
                Document.is_active.is_(True),
            )
            .values(is_active=False)
        )
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[attr-defined]
