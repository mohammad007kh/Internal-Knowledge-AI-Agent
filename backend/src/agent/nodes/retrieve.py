"""retrieve_context — LangGraph node that embeds the user query and fetches
the top-K most relevant chunks, scoped to the caller's allowed source IDs.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

from src.agent.state import AgentState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chunk_repository import ChunkRepository
    from src.services.embedding_service_factory import EmbeddingServiceFactory

logger = logging.getLogger(__name__)

_RESULT_LIMIT = 10
SIMILARITY_THRESHOLD = 0.4


async def retrieve_context(
    state: AgentState,
    *,
    embedding_service_factory: EmbeddingServiceFactory,
    chunk_repository: ChunkRepository,
    db_session: AsyncSession,
    langfuse: Langfuse,
) -> dict:  # type: ignore[type-arg]
    """Embed the user query and retrieve the top-K most relevant chunks.

    Enforces FR-019: only chunks whose source_id appears in
    ``state["source_ids"]`` are ever returned.

    The active embedder record drives both the query embedding and the
    defensive ``embedder_id`` filter on the SQL similarity search — see
    §6.3 of the design doc.
    """
    source_ids: list[str] = state.get("source_ids", [])
    query: str = state.get("query", "").strip()

    # FR-019: empty allowlist → no results, no embedding call
    if not source_ids:
        logger.warning(
            "retrieve_context: empty source_ids for user=%s — returning empty",
            state.get("user_id"),
        )
        return {"retrieved_chunks": []}

    if not query:
        return {"retrieved_chunks": []}

    span = langfuse.start_span(
        name="retrieve_context",
        input={"query": query, "source_ids": source_ids},
    )

    try:
        # ``for_active`` returns both the service and the active embedder id
        # in one call so the retrieve node can apply the defensive
        # ``embedder_id`` filter without a duplicate DB roundtrip.
        embedding_service, active_id = await embedding_service_factory.for_active()
        query_embedding: list[float] = await embedding_service.embed_query(query)

        pairs = await chunk_repository.similarity_search(
            db_session,
            query_embedding=query_embedding,
            source_ids=source_ids,
            limit=_RESULT_LIMIT,
            embedder_id=active_id,
        )

        chunks = [
            {
                "chunk_id": str(chunk.id),
                "source_id": str(chunk.source_id),
                "text": chunk.chunk_text,
                "score": round(score, 4),
            }
            for chunk, score in pairs
            if score < SIMILARITY_THRESHOLD
        ]

        if not chunks:
            logger.info(
                "retrieve_context: all %d chunks scored ≥ %.2f distance threshold — no relevant context",
                len(pairs),
                SIMILARITY_THRESHOLD,
            )
            span.update(output={"chunk_count": 0, "below_threshold": True})
            return {"retrieved_chunks": []}

        span.update(output={"chunk_count": len(chunks)})
        logger.info(
            "retrieve_context: found %d chunks (above threshold) for query len=%d",
            len(chunks),
            len(query),
        )
        return {"retrieved_chunks": chunks}

    except Exception:
        logger.exception("retrieve_context failed")
        span.update(output={"chunk_count": 0, "error": True})
        return {"retrieved_chunks": [], "error": "retrieval_failed"}
    finally:
        span.end()
