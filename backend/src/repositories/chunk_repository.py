"""CRUD + vector-search repository for the Chunk ORM model."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
from sqlalchemy import bindparam, delete, func, select, text
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
        embedder_id: uuid.UUID | None = None,
    ) -> list[tuple[Chunk, float]]:
        """
        HNSW cosine similarity search filtered by source_ids (FR-019).

        The operator is ``<=>`` (cosine distance) — matching the
        ``vector_cosine_ops`` HNSW index built in revision 0007.  Using
        ``<->`` (L2) here forced sequential scans (see design doc §6.2).

        Args:
            session:         Async SQLAlchemy session (injected per-call).
            query_embedding: Embedded query vector (must be EMBEDDING_DIM floats).
            source_ids:      Allowlist of source ID strings.  Empty list causes
                             an immediate empty-list return (no DB query).
            limit:           Maximum number of results to return (default 10).
            embedder_id:     When provided, restricts results to chunks
                             produced by this embedder.  Defensive guard
                             for v1.1 cross-embedder isolation.

        Returns:
            List of (Chunk, cosine_distance) tuples ordered by distance asc.
        """
        if not source_ids:
            return []

        # SECURITY: the query embedding MUST be passed via a typed bindparam,
        # never interpolated into the SQL string.  pgvector's SQLAlchemy
        # adapter serialises ``list[float]`` → ``vector`` correctly when the
        # bind is typed with ``Vector``; we additionally ``CAST(:qvec AS
        # vector)`` so pgvector picks the right operator class even if the
        # adapter doesn't kick in (e.g. raw asyncpg fast-path).
        embedder_clause = ""
        extra_binds: list[object] = []
        if embedder_id is not None:
            embedder_clause = " AND c.embedder_id = :embedder_id"
            extra_binds.append(
                bindparam("embedder_id", value=str(embedder_id))
            )

        stmt = text(
            f"""
            SELECT
                c.id        AS chunk_id,
                c.source_id,
                c.chunk_text,
                c.embedding <=> CAST(:qvec AS vector)  AS score
            FROM chunks c
            WHERE c.source_id = ANY(:source_ids){embedder_clause}
            ORDER BY score ASC
            LIMIT :limit
            """
        ).bindparams(
            bindparam("qvec", value=query_embedding, type_=Vector()),
            bindparam("source_ids", value=source_ids),
            bindparam("limit", value=limit),
            *extra_binds,
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
