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
        mock_langfuse.span.return_value = mock_span

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
        mock_langfuse.span.return_value = MagicMock()

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
        mock_langfuse.span.assert_not_called()

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

    async def test_prefers_selected_source_ids_over_full_allowlist(self, base_state):
        """source_router output must filter retrieval; bug fix for Slice E defect 1.

        When ``selected_source_ids`` is non-empty it is a subset chosen by the
        v2 router LLM.  ``similarity_search`` must be called with that subset
        — not the full ``source_ids`` allowlist — otherwise the router is
        theatre and the LLM filtering does nothing.
        """
        uuid_a = "11111111-1111-1111-1111-111111111111"
        uuid_b = "22222222-2222-2222-2222-222222222222"
        uuid_c = "33333333-3333-3333-3333-333333333333"
        base_state["source_ids"] = [uuid_a, uuid_b, uuid_c]
        base_state["selected_source_ids"] = [uuid_a]

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536

        from src.models.chunk import Chunk  # noqa: PLC0415

        fake_chunk = MagicMock(spec=Chunk)
        fake_chunk.id = "chunk-1"
        fake_chunk.source_id = uuid_a
        fake_chunk.chunk_text = "Only-A content."
        fake_chunk.metadata_ = {}

        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        # similarity_search was called with the selected subset, NOT the
        # broader allowlist.
        kwargs = mock_chunk_repo.similarity_search.await_args.kwargs
        assert kwargs["source_ids"] == [uuid_a]
        # And only the chunk from uuid_a comes back.
        assert len(result["retrieved_chunks"]) == 1
        assert result["retrieved_chunks"][0]["source_id"] == uuid_a

    async def test_falls_back_to_source_ids_when_selected_empty(self, base_state):
        """v1 path / degraded router writes empty selected_source_ids."""
        base_state["source_ids"] = ["src-1", "src-2"]
        base_state["selected_source_ids"] = []

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536
        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.return_value = []
        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        kwargs = mock_chunk_repo.similarity_search.await_args.kwargs
        assert kwargs["source_ids"] == ["src-1", "src-2"]
