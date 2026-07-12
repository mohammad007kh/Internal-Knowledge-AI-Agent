"""Unit tests for the FX37 schema-context injection in retrieve_context.

The retrieve node was rewritten to:

1. Preserve any ``retrieved_chunks`` an upstream node (text_to_query)
   already produced — historically the bare ``return {"retrieved_chunks":
   chunks}`` here clobbered them.
2. Prepend schema-context chunks for every DB source in
   ``selected_source_ids`` so the synthesizer prompt is grounded in the
   actual schema even when vector search returns nothing.

These tests cover both behaviours.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# Same env-var preamble as the rest of the agent unit suite.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402

from src.agent.nodes.retrieve import retrieve_context  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _schema_chunk(source_id: str, text: str = "schema text") -> dict:
    # Pinned schema context carries no score key (FX41) — mirrors
    # _build_chunk_dict in src/agent/nodes/_schema_context.py.
    return {
        "chunk_id": f"schema:{source_id}",
        "source_id": source_id,
        "text": text,
        "document_title": "x — schema overview",
        "page_number": None,
        "source_name": "x",
    }


def _sql_row_chunk(source_id: str, idx: int = 0) -> dict:
    return {
        "chunk_id": f"sql:{source_id}:{idx}",
        "source_id": source_id,
        "text": f"row {idx}",
        "score": 0.0,
        "document_title": "x",
        "page_number": None,
        "source_name": "x",
    }


def _factory_with(embedding_service: AsyncMock) -> AsyncMock:
    factory = AsyncMock()
    factory.for_active.return_value = (embedding_service, uuid.uuid4())
    return factory


def _langfuse_mock() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


# ---------------------------------------------------------------------------
# Schema-chunk injection — the core FX37 property
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_chunks_prepended_when_vector_search_finds_nothing() -> None:
    """The bug: DB sources have no rows in ``chunks`` so vector search
    returns []. Before FX37 the synthesizer saw an empty context and
    replied with a generic greeting. After FX37 the studying-agent's
    schema doc rides into the context as a synthetic chunk.
    """
    source_id = str(uuid.uuid4())
    schema = _schema_chunk(source_id, text="Database source: cctp-db")

    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = []  # no vector hits

    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "Please tell me about this database.",
        "source_ids": [source_id],
        "selected_source_ids": [source_id],
        "retrieved_chunks": [],
        "messages": [],
    }

    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[schema]),
    ) as mock_load:
        result = await retrieve_context(
            state,
            embedding_service_factory=_factory_with(embedding),
            chunk_repository=chunk_repo,
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    chunks = result["retrieved_chunks"]
    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == f"schema:{source_id}"
    assert "Database source: cctp-db" in chunks[0]["text"]
    mock_load.assert_awaited_once()


@pytest.mark.asyncio
async def test_schema_and_vector_chunks_coexist_in_result() -> None:
    source_id = str(uuid.uuid4())
    schema = _schema_chunk(source_id)

    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536

    fake_chunk = MagicMock()
    fake_chunk.id = "vec-1"
    fake_chunk.source_id = source_id
    fake_chunk.chunk_text = "some semantically-retrieved sentence"
    fake_chunk.metadata_ = {"document_title": "manual.pdf"}
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "what's in this database?",
        "source_ids": [source_id],
        "selected_source_ids": [source_id],
        "retrieved_chunks": [],
        "messages": [],
    }

    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[schema]),
    ):
        result = await retrieve_context(
            state,
            embedding_service_factory=_factory_with(embedding),
            chunk_repository=chunk_repo,
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    ids = [c["chunk_id"] for c in result["retrieved_chunks"]]
    assert f"schema:{source_id}" in ids
    assert "vec-1" in ids
    # Schema chunk comes first — it's the most deterministic grounding.
    assert ids[0] == f"schema:{source_id}"


@pytest.mark.asyncio
async def test_upstream_text_to_query_chunks_preserved() -> None:
    """Regression: a previous bug had retrieve_context overwriting any
    chunks text_to_query had already loaded into state. With FX37 we
    explicitly merge them.
    """
    source_id = str(uuid.uuid4())
    sql_row = _sql_row_chunk(source_id, idx=0)

    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = []  # no vector hits

    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "select rows from this DB",
        "source_ids": [source_id],
        "selected_source_ids": [source_id],
        "retrieved_chunks": [sql_row],  # text_to_query already populated this
        "messages": [],
    }

    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[]),
    ):
        result = await retrieve_context(
            state,
            embedding_service_factory=_factory_with(embedding),
            chunk_repository=chunk_repo,
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    ids = [c["chunk_id"] for c in result["retrieved_chunks"]]
    assert sql_row["chunk_id"] in ids


@pytest.mark.asyncio
async def test_dedupes_schema_chunks_across_paths() -> None:
    """If the same schema chunk were ever added twice (state preserved AND
    re-emitted), the merge must dedupe by chunk_id."""
    source_id = str(uuid.uuid4())
    schema = _schema_chunk(source_id)

    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = []

    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "...",
        "source_ids": [source_id],
        "selected_source_ids": [source_id],
        "retrieved_chunks": [schema],  # already present as upstream
        "messages": [],
    }

    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[schema]),
    ):
        result = await retrieve_context(
            state,
            embedding_service_factory=_factory_with(embedding),
            chunk_repository=chunk_repo,
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    ids = [c["chunk_id"] for c in result["retrieved_chunks"]]
    assert ids.count(f"schema:{source_id}") == 1


@pytest.mark.asyncio
async def test_schema_chunks_returned_even_when_no_base_query() -> None:
    """Empty base query → retrieval normally short-circuits to []. The
    schema chunk must still ride through so the synthesizer has something
    to ground on (e.g. greeting-only sessions on a DB Test tab)."""
    source_id = str(uuid.uuid4())
    schema = _schema_chunk(source_id)

    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "",  # no query
        "source_ids": [source_id],
        "selected_source_ids": [source_id],
        "retrieved_chunks": [],
        "messages": [],
    }

    embedding = AsyncMock()
    chunk_repo = AsyncMock()
    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[schema]),
    ):
        result = await retrieve_context(
            state,
            embedding_service_factory=_factory_with(embedding),
            chunk_repository=chunk_repo,
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["chunk_id"] == f"schema:{source_id}"


@pytest.mark.asyncio
async def test_no_schema_call_when_source_ids_empty() -> None:
    """Empty allowlist → no DB query for schema chunks (cheap path)."""
    state = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "anything",
        "source_ids": [],
        "selected_source_ids": [],
        "retrieved_chunks": [],
        "messages": [],
    }

    with patch(
        "src.agent.nodes.retrieve.load_schema_context_chunks",
        AsyncMock(return_value=[]),
    ) as mock_load:
        result = await retrieve_context(
            state,
            embedding_service_factory=AsyncMock(),
            chunk_repository=AsyncMock(),
            db_session=AsyncMock(),
            langfuse=_langfuse_mock(),
        )

    # The helper itself is called but with empty list → returns [] cheaply.
    mock_load.assert_awaited_once()
    assert result["retrieved_chunks"] == []
