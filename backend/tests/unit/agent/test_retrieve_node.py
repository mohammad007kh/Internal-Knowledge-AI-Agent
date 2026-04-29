"""Unit tests for the retrieve_context LangGraph node."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.retrieve import retrieve_context


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


def _factory_with(embedding_service: AsyncMock) -> AsyncMock:
    """Build a fake :class:`EmbeddingServiceFactory` returning *embedding_service*."""
    factory = AsyncMock()
    # ``for_active`` now returns ``(service, embedder_id)`` — see
    # EmbeddingServiceFactory.for_active().
    factory.for_active.return_value = (embedding_service, uuid.uuid4())
    return factory


@pytest.mark.asyncio
class TestRetrieveContext:
    async def test_returns_chunks(self, base_state):
        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536

        from src.models.chunk import Chunk  # noqa: PLC0415

        fake_chunk = MagicMock(spec=Chunk)
        fake_chunk.id = "chunk-1"
        fake_chunk.source_id = "src-1"
        fake_chunk.chunk_text = "Refunds are processed within 30 days."
        fake_chunk.metadata_ = {
            "document_title": "Refund Policy.pdf",
            "page_number": 3,
            "source_name": "Knowledge Base",
        }

        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

        mock_langfuse = MagicMock()
        mock_span = MagicMock()
        mock_langfuse.start_span.return_value = mock_span

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        assert len(result["retrieved_chunks"]) == 1
        chunk_dict = result["retrieved_chunks"][0]
        assert chunk_dict["text"] == "Refunds are processed within 30 days."
        # A.2 — chunk dict projects metadata_ keys for persist.py to render
        # human-readable citations instead of UUIDs.
        assert chunk_dict["document_title"] == "Refund Policy.pdf"
        assert chunk_dict["page_number"] == 3
        assert chunk_dict["source_name"] == "Knowledge Base"
        mock_span.end.assert_called_once()

    async def test_chunk_with_null_metadata_renders_none_keys(self, base_state):
        """Older chunks without metadata_ degrade gracefully to None keys."""
        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536

        from src.models.chunk import Chunk  # noqa: PLC0415

        fake_chunk = MagicMock(spec=Chunk)
        fake_chunk.id = "chunk-1"
        fake_chunk.source_id = "src-1"
        fake_chunk.chunk_text = "Old chunk without metadata."
        fake_chunk.metadata_ = None  # JSONB column may be NULL on legacy rows

        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

        mock_langfuse = MagicMock()
        mock_langfuse.start_span.return_value = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        chunk_dict = result["retrieved_chunks"][0]
        assert chunk_dict["document_title"] is None
        assert chunk_dict["page_number"] is None
        assert chunk_dict["source_name"] is None

    async def test_empty_source_ids_returns_empty(self, base_state):
        base_state["source_ids"] = []

        mock_langfuse = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=AsyncMock(),
            chunk_repository=AsyncMock(),
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        assert result["retrieved_chunks"] == []
        mock_langfuse.start_span.assert_not_called()

    async def test_empty_query_returns_empty(self, base_state):
        base_state["query"] = "   "

        result = await retrieve_context(
            base_state,
            embedding_service_factory=AsyncMock(),
            chunk_repository=AsyncMock(),
            db_session=AsyncMock(),
            langfuse=MagicMock(),
        )

        assert result["retrieved_chunks"] == []
