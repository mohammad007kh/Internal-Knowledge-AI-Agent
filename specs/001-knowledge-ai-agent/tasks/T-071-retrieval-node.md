# T-071 — LangGraph Retrieval Node

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs
LangGraph 8-node · interrupt() for clarification · SSE streaming
Langfuse self-hosted · every pipeline run must emit a trace
RFC 7807 Problem Details — all non-2xx API responses
FR-019: source access per user per source — NEVER expose unapproved data
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
```

## Goal
Implement the **`retrieve_context` LangGraph node** that performs pgvector
similarity search filtered strictly to the user's allowlisted sources
(FR-019 enforcement).

Key responsibilities:
1. Embed the user query via `EmbeddingService`
2. Call `ChunkRepository.similarity_search()` with `source_ids` filter
3. Populate `state["retrieved_chunks"]`
4. Emit a Langfuse span with input query + output chunk count

---

## Acceptance Criteria

- [ ] `retrieve_context` node returns `retrieved_chunks` populated with ≤10 items
- [ ] Each item has keys: `chunk_id`, `source_id`, `text`, `score`
- [ ] When `source_ids` is empty, returns empty list immediately (no DB query)
- [ ] `ChunkRepository.similarity_search()` uses `<->` cosine operator with HNSW hint
- [ ] Langfuse span `"retrieve_context"` emitted with `input=query`, `output=chunk_count`
- [ ] Unit test: mock `EmbeddingService` + `ChunkRepository`; assert `retrieved_chunks` length ≤ 10

---

## 1  `app/repositories/chunk_repository.py` — `similarity_search` method

Add to the existing `ChunkRepository` (T-052):

```python
# app/repositories/chunk_repository.py
# --- append after existing methods ---

from pgvector.sqlalchemy import Vector
from sqlalchemy import text


async def similarity_search(
    self,
    session: AsyncSession,
    *,
    query_embedding: list[float],
    source_ids: list[str],
    limit: int = 10,
) -> list[tuple[Chunk, float]]:
    """Return chunks most similar to ``query_embedding``.

    Parameters
    ----------
    query_embedding:
        Float list of length 1536 produced by ``EmbeddingService``.
    source_ids:
        Allowlist of source UUIDs (FR-019).  Must be non-empty — callers
        MUST validate before calling this method.
    limit:
        Maximum number of results (default 10).

    Returns
    -------
    List of (Chunk, cosine_distance) tuples sorted ascending by distance
    (smaller = more similar).
    """
    if not source_ids:
        return []

    # Cast Python list to PG vector literal
    vector_literal = f"'[{','.join(str(v) for v in query_embedding)}]'::vector"

    # Use raw SQL for the distance operator; SQLAlchemy doesn't natively
    # support <-> without pgvector extension wiring.
    stmt = text(
        f"""
        SELECT
            c.id           AS chunk_id,
            c.source_id,
            c.text,
            c.embedding <-> {vector_literal}  AS score
        FROM chunks c
        WHERE c.source_id = ANY(:source_ids)
          AND c.is_deleted IS NOT TRUE
        ORDER BY score ASC
        LIMIT :limit
        """
    ).bindparams(
        source_ids=source_ids,
        limit=limit,
    )

    result = await session.execute(stmt)
    rows = result.mappings().all()

    # Hydrate full Chunk objects to keep return type consistent
    chunk_ids = [str(r["chunk_id"]) for r in rows]
    score_map = {str(r["chunk_id"]): float(r["score"]) for r in rows}

    if not chunk_ids:
        return []

    hydrated = await session.execute(
        select(Chunk).where(Chunk.id.in_(chunk_ids))
    )
    chunks_by_id = {c.id: c for c in hydrated.scalars().all()}

    # Preserve similarity ordering
    return [
        (chunks_by_id[cid], score_map[cid])
        for cid in chunk_ids
        if cid in chunks_by_id
    ]
```

---

## 2  `app/agent/nodes/retrieve.py`

```python
# app/agent/nodes/retrieve.py
"""retrieve_context — LangGraph node."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langfuse import Langfuse

from app.agent.state import AgentState

if TYPE_CHECKING:
    from app.repositories.chunk_repository import ChunkRepository
    from app.services.embedding_service import EmbeddingService
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_RESULT_LIMIT = 10


async def retrieve_context(
    state: AgentState,
    *,
    embedding_service: "EmbeddingService",
    chunk_repository: "ChunkRepository",
    db_session: "AsyncSession",
    langfuse: "Langfuse",
) -> dict:
    """Embed the user query and retrieve the top-K most relevant chunks.

    Enforces FR-019: only chunks whose source_id appears in
    ``state["source_ids"]`` are ever returned.
    """
    source_ids: list[str] = state.get("source_ids", [])
    query: str = state.get("query", "").strip()

    # FR-019: empty allowlist → no results
    if not source_ids:
        logger.warning(
            "retrieve_context: empty source_ids for user=%s — returning empty",
            state.get("user_id"),
        )
        return {"retrieved_chunks": []}

    if not query:
        return {"retrieved_chunks": []}

    span = langfuse.span(
        trace_id=state["trace_id"],
        name="retrieve_context",
        input={"query": query, "source_ids": source_ids},
    )

    try:
        # Step 1 — embed query
        embeddings = await embedding_service.embed_texts([query])
        query_embedding = embeddings[0]

        # Step 2 — similarity search (source-filtered)
        pairs = await chunk_repository.similarity_search(
            db_session,
            query_embedding=query_embedding,
            source_ids=source_ids,
            limit=_RESULT_LIMIT,
        )

        chunks = [
            {
                "chunk_id": str(chunk.id),
                "source_id": str(chunk.source_id),
                "text": chunk.text,
                "score": round(score, 4),
            }
            for chunk, score in pairs
        ]

        span.update(output={"chunk_count": len(chunks)})
        logger.info(
            "retrieve_context: found %d chunks for query len=%d",
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
```

---

## 3  `app/agent/nodes/__init__.py`

```python
# app/agent/nodes/__init__.py
"""LangGraph node implementations."""
from app.agent.nodes.retrieve import retrieve_context  # noqa: F401
```

---

## 4  `app/agent/pipeline.py` — patch (replace stub)

Replace the stub `retrieve_context` definition:

```python
# Remove:
async def retrieve_context(state: AgentState) -> dict:
    """Semantic search over allowlisted sources and populate retrieved_chunks."""
    logger.debug("node=retrieve_context query=%s", state.get("query", ""))
    return {"retrieved_chunks": []}

# Replace with import at top of file:
from app.agent.nodes.retrieve import retrieve_context  # noqa: F401
```

> **Note:** The node signature in `pipeline.py` must use `functools.partial` to
> inject dependencies when building the graph.  Full injection is done in T-074.

---

## 5  Unit Tests — `tests/unit/agent/test_retrieve_node.py`

```python
# tests/unit/agent/test_retrieve_node.py
"""Unit tests for the retrieve_context LangGraph node."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.nodes.retrieve import retrieve_context


@pytest.fixture()
def base_state():
    return {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "What is our refund policy?",
        "source_ids": ["src-1", "src-2"],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [],
        "final_answer": None,
        "error": None,
    }


@pytest.mark.asyncio
async def test_returns_chunks(base_state):
    mock_embedding_service = AsyncMock()
    mock_embedding_service.embed_texts.return_value = [[0.1] * 1536]

    from app.models.chunk import Chunk  # noqa: PLC0415

    fake_chunk = MagicMock(spec=Chunk)
    fake_chunk.id = "chunk-1"
    fake_chunk.source_id = "src-1"
    fake_chunk.text = "Refunds are processed within 30 days."

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

    mock_langfuse = MagicMock()
    mock_span = MagicMock()
    mock_langfuse.span.return_value = mock_span

    result = await retrieve_context(
        base_state,
        embedding_service=mock_embedding_service,
        chunk_repository=mock_chunk_repo,
        db_session=AsyncMock(),
        langfuse=mock_langfuse,
    )

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "Refunds are processed within 30 days."
    mock_span.end.assert_called_once()


@pytest.mark.asyncio
async def test_empty_source_ids_returns_empty(base_state):
    base_state["source_ids"] = []

    mock_langfuse = MagicMock()

    result = await retrieve_context(
        base_state,
        embedding_service=AsyncMock(),
        chunk_repository=AsyncMock(),
        db_session=AsyncMock(),
        langfuse=mock_langfuse,
    )

    assert result["retrieved_chunks"] == []
    # No DB query attempted
    mock_langfuse.span.assert_not_called()


@pytest.mark.asyncio
async def test_empty_query_returns_empty(base_state):
    base_state["query"] = "   "

    result = await retrieve_context(
        base_state,
        embedding_service=AsyncMock(),
        chunk_repository=AsyncMock(),
        db_session=AsyncMock(),
        langfuse=MagicMock(),
    )

    assert result["retrieved_chunks"] == []
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| PATCH  | `app/repositories/chunk_repository.py` |
| CREATE | `app/agent/nodes/__init__.py` |
| CREATE | `app/agent/nodes/retrieve.py` |
| PATCH  | `app/agent/pipeline.py` |
| CREATE | `tests/unit/agent/test_retrieve_node.py` |
