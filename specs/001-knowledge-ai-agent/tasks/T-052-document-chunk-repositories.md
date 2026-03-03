# T-052 â€” DocumentRepository & ChunkRepository

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x (async) Â· Pydantic v2 Â· dependency-injector
PostgreSQL 16 + pgvector Â· HNSW (m=16, ef_construction=64)
UUID PKs Â· soft-delete on documents Â· Alembic migrations
RFC 7807 Problem Details â€” all non-2xx API responses
```

## Goal
Implement `DocumentRepository` and `ChunkRepository` following the same patterns
established in T-041 (`SourceRepository`): typed async methods, no raw SQL in service
layer, and vector similarity search encapsulated behind a clean repository interface.

---

## File 1 â€” `app/repositories/document_repository.py`

```python
"""CRUD repository for the Document ORM model."""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    """
    All Document database access is funnelled through this repository.
    Soft-delete: callers call `soft_delete()` â€” hard DELETE is only used
    by cascade when the parent Source is deleted.
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
        """Soft-delete all documents for a source. Returns affected row count."""
        stmt = (
            update(Document)
            .where(
                Document.source_id == source_id,
                Document.is_active.is_(True),
            )
            .values(is_active=False)
        )
        result = await self._session.execute(stmt)
        return result.rowcount
```

---

## File 2 â€” `app/repositories/chunk_repository.py`

```python
"""CRUD + vector-search repository for the Chunk ORM model."""
from __future__ import annotations

import uuid
from typing import Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import EMBEDDING_DIM, Chunk


class ChunkRepository:
    """
    All Chunk database access â€” including HNSW cosine similarity search â€”
    is encapsulated here.  Service layer never touches raw SQL.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(self, chunk_id: uuid.UUID) -> Chunk | None:
        stmt = select(Chunk).where(Chunk.id == chunk_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_document(
        self,
        document_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> Sequence[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_by_source(self, source_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(Chunk.source_id == source_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def similarity_search(
        self,
        query_embedding: list[float],
        *,
        source_ids: list[uuid.UUID] | None = None,
        top_k: int = 5,
        ef_search: int = 64,
    ) -> list[tuple[Chunk, float]]:
        """
        HNSW cosine similarity search.

        Args:
            query_embedding: Embedded query vector (must be EMBEDDING_DIM floats).
            source_ids:      Optional list of source UUIDs to restrict search.
                             If None or empty, searches all chunks.
            top_k:           Number of results to return.
            ef_search:       HNSW ef_search parameter (higher = more accurate,
                             slower). Sent per-session via SET LOCAL.

        Returns:
            List of (Chunk, cosine_distance) tuples ordered by distance asc.
        """
        if len(query_embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"query_embedding must have {EMBEDDING_DIM} dimensions, "
                f"got {len(query_embedding)}"
            )

        # Set ef_search for this query; uses SET LOCAL so it doesn't bleed
        # across transactions.
        await self._session.execute(
            text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
        )

        # Build base query using pgvector's <=> cosine distance operator.
        embedding_col = Chunk.embedding
        distance_expr = embedding_col.op("<=>")(
            Vector(query_embedding)
        ).label("distance")

        stmt = select(Chunk, distance_expr).order_by(distance_expr).limit(top_k)

        if source_ids:
            stmt = stmt.where(Chunk.source_id.in_(source_ids))

        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row[0], float(row[1])) for row in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def bulk_create(self, chunks: list[Chunk]) -> list[Chunk]:
        self._session.add_all(chunks)
        await self._session.flush()
        return chunks

    async def delete_by_document(self, document_id: uuid.UUID) -> int:
        """Hard-delete all chunks for a document. Returns affected row count."""
        stmt = delete(Chunk).where(Chunk.document_id == document_id)
        result = await self._session.execute(stmt)
        return result.rowcount

    async def delete_by_source(self, source_id: uuid.UUID) -> int:
        """Hard-delete all chunks for a source. Returns affected row count."""
        stmt = delete(Chunk).where(Chunk.source_id == source_id)
        result = await self._session.execute(stmt)
        return result.rowcount
```

---

## File 3 â€” `app/containers.py` (patch)

Register both repositories as `Factory` providers:

```python
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository

# Inside ApplicationContainer:
document_repository = providers.Factory(
    DocumentRepository,
    session=db_session,
)

chunk_repository = providers.Factory(
    ChunkRepository,
    session=db_session,
)
```

---

## Acceptance Criteria

1. `DocumentRepository` is importable from `app.repositories.document_repository`.
2. `ChunkRepository` is importable from `app.repositories.chunk_repository`.
3. `similarity_search` raises `ValueError` when `query_embedding` length â‰  1536.
4. `similarity_search` issues `SET LOCAL hnsw.ef_search = N` before the SELECT.
5. `bulk_create` on `ChunkRepository` inserts multiple rows in one flush.
6. `soft_delete_by_source` on `DocumentRepository` updates `is_active=False` and
   returns the number of affected rows.
7. `delete_by_source` on `ChunkRepository` hard-deletes and returns the row count.
8. Both repositories are registered as `providers.Factory` in the DI container.
9. Neither repository imports from service files (no upward dependency).
