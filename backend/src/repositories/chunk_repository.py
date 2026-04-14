"""CRUD + vector-search repository for the Chunk ORM model."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk import Chunk


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
        session: AsyncSession,
        *,
        query_embedding: list[float],
        source_ids: list[str],
        limit: int = 10,
    ) -> list[tuple[Chunk, float]]:
        """
        HNSW cosine similarity search filtered by source_ids (FR-019).

        Args:
            session:         Async SQLAlchemy session (injected per-call).
            query_embedding: Embedded query vector (must be EMBEDDING_DIM floats).
            source_ids:      Allowlist of source ID strings.  Empty list causes
                             an immediate empty-list return (no DB query).
            limit:           Maximum number of results to return (default 10).

        Returns:
            List of (Chunk, cosine_distance) tuples ordered by distance asc.
        """
        if not source_ids:
            return []

        vector_literal = f"'[{','.join(str(v) for v in query_embedding)}]'::vector"

        stmt = text(
            f"""
            SELECT
                c.id        AS chunk_id,
                c.source_id,
                c.chunk_text,
                c.embedding <-> {vector_literal}  AS score
            FROM chunks c
            WHERE c.source_id = ANY(:source_ids)
            ORDER BY score ASC
            LIMIT :limit
            """
        ).bindparams(
            source_ids=source_ids,
            limit=limit,
        )

        result = await session.execute(stmt)
        rows = result.mappings().all()

        chunk_ids = [str(r["chunk_id"]) for r in rows]
        score_map = {str(r["chunk_id"]): float(r["score"]) for r in rows}

        if not chunk_ids:
            return []

        hydrated = await session.execute(
            select(Chunk).where(Chunk.id.in_(chunk_ids))
        )
        chunks_by_id = {str(c.id): c for c in hydrated.scalars().all()}

        # Preserve similarity ordering
        return [
            (chunks_by_id[cid], score_map[cid])
            for cid in chunk_ids
            if cid in chunks_by_id
        ]

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
