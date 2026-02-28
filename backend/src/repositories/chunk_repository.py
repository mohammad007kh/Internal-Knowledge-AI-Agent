"""CRUD + vector-search repository for the Chunk ORM model."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk import EMBEDDING_DIM, Chunk


class ChunkRepository:
    """
    All Chunk database access — including HNSW cosine similarity search —
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
        distance_expr = embedding_col.op("<=>")(  # type: ignore[union-attr]
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
        return result.rowcount  # type: ignore[attr-defined]

    async def delete_by_source(self, source_id: uuid.UUID) -> int:
        """Hard-delete all chunks for a source. Returns affected row count."""
        stmt = delete(Chunk).where(Chunk.source_id == source_id)
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[attr-defined]
