"""Unit tests for the retrieve_context LangGraph node."""
from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from src.agent.nodes import retrieve as retrieve_module
from src.agent.nodes.retrieve import SIMILARITY_THRESHOLD, retrieve_context


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

    # ------------------------------------------------------------------
    # FX5 regression tests
    # ------------------------------------------------------------------

    async def test_embeds_all_query_variants(self, base_state):
        """FX5/RC1: every variant produced by the analyzer is embedded."""
        base_state["query_variants"] = ["a", "b", "c"]
        base_state["query"] = "a"  # base matches first variant — no extra prepend

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

        # embed_query is called once per variant.
        assert mock_embedding_service.embed_query.await_count == 3
        called_with = [
            call.args[0] for call in mock_embedding_service.embed_query.await_args_list
        ]
        assert called_with == ["a", "b", "c"]

    async def test_merges_variants_keeping_min_distance(self, base_state):
        """FX5/RC1: when two variants surface the same chunk, the merged
        result must keep the minimum distance and surface the chunk only
        once.
        """
        base_state["query_variants"] = ["v1", "v2"]
        base_state["query"] = "v1"

        from src.models.chunk import Chunk  # noqa: PLC0415

        chunk = MagicMock(spec=Chunk)
        chunk.id = "chunk-shared"
        chunk.source_id = "src-1"
        chunk.chunk_text = "Shared content."
        chunk.metadata_ = {}

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536

        # First variant returns the chunk at distance 0.7; second at 0.4.
        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.side_effect = [
            [(chunk, 0.7)],
            [(chunk, 0.4)],
        ]

        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        assert len(result["retrieved_chunks"]) == 1
        # min(0.7, 0.4) = 0.4 — the merged distance must be the lower one.
        assert result["retrieved_chunks"][0]["score"] == pytest.approx(0.4)

    async def test_threshold_default_is_0_85(self):
        """FX5/RC2: pin the new cosine-distance ceiling."""
        assert SIMILARITY_THRESHOLD == 0.85

    async def test_score_distribution_logged_even_when_all_dropped(
        self, base_state, caplog
    ):
        """FX5/RC2: ``retrieve.score_distribution`` is always emitted, so
        ``"why no chunks?"`` debugging never depends on Langfuse pivots.
        """
        from src.models.chunk import Chunk  # noqa: PLC0415

        chunk = MagicMock(spec=Chunk)
        chunk.id = "chunk-1"
        chunk.source_id = "src-1"
        chunk.chunk_text = "Some text."
        chunk.metadata_ = {}

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.return_value = [0.1] * 1536
        mock_chunk_repo = AsyncMock()
        # All distances above 0.85 → everything dropped.
        mock_chunk_repo.similarity_search.return_value = [
            (chunk, 0.95),
            (chunk, 0.92),
            (chunk, 0.91),
        ]
        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        with caplog.at_level(logging.INFO, logger=retrieve_module.__name__):
            result = await retrieve_context(
                base_state,
                embedding_service_factory=_factory_with(mock_embedding_service),
                chunk_repository=mock_chunk_repo,
                db_session=AsyncMock(),
                langfuse=mock_langfuse,
            )

        assert result["retrieved_chunks"] == []
        score_lines = [
            r.getMessage()
            for r in caplog.records
            if "retrieve.score_distribution" in r.getMessage()
        ]
        assert len(score_lines) == 1, (
            "expected exactly one retrieve.score_distribution log even on full drop"
        )
        msg = score_lines[0]
        assert "kept=0" in msg
        assert "dropped=" in msg

    async def test_concatenates_prior_turns_when_analyzer_degraded(self, base_state):
        """FX5/RC4 stop-gap: when the analyzer degraded, the embedding query
        must include the previous user turns to give retrieval a fighting
        chance at recovering pronoun references.
        """
        base_state["query"] = "Does that project have a boss?"
        base_state["query_variants"] = ["Does that project have a boss?"]
        base_state["query_analyzer_degraded"] = True
        base_state["messages"] = [
            HumanMessage(content="What's the cctp about?"),
            HumanMessage(content="Who is in charge for that project?"),
            HumanMessage(content="Does that project have a boss?"),
        ]

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

        embedded_strings = [
            call.args[0] for call in mock_embedding_service.embed_query.await_args_list
        ]
        # The augmented query (joined by " | ") must be embedded as the
        # first (or only) query.
        augmented = embedded_strings[0]
        assert " | " in augmented
        assert "Who is in charge for that project?" in augmented
        assert "Does that project have a boss?" in augmented
        # And it must NOT contain the current turn duplicated — the
        # _last_user_turn_texts(exclude=base_query) filter drops it.
        assert augmented.count("Does that project have a boss?") == 1

    async def test_one_failing_embedding_variant_does_not_kill_retrieval(
        self, base_state
    ):
        """FX5 follow-up: when 1 of N variants fails to embed, the others
        still proceed and the merged result is non-empty.
        """
        base_state["query"] = "a"
        base_state["query_variants"] = ["a", "b"]

        from src.models.chunk import Chunk  # noqa: PLC0415

        chunk = MagicMock(spec=Chunk)
        chunk.id = "chunk-1"
        chunk.source_id = "src-1"
        chunk.chunk_text = "ok"
        chunk.metadata_ = {}

        mock_embedding_service = AsyncMock()

        async def embed_side_effect(q: str):
            if q == "a":
                raise RuntimeError("embed boom")
            return [0.1] * 1536

        mock_embedding_service.embed_query.side_effect = embed_side_effect

        mock_chunk_repo = AsyncMock()
        mock_chunk_repo.similarity_search.return_value = [(chunk, 0.4)]

        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        assert len(result["retrieved_chunks"]) == 1
        # similarity_search ran once (only the surviving embedding).
        assert mock_chunk_repo.similarity_search.await_count == 1

    async def test_all_embeddings_failing_raises_to_outer_handler(self, base_state):
        """FX5 follow-up: if every variant fails, retrieve_context surfaces
        an error (not a silent empty result) so the outer handler can
        record state["error"]="retrieval_failed".
        """
        base_state["query"] = "a"
        base_state["query_variants"] = ["a", "b"]

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed_query.side_effect = RuntimeError("all fail")
        mock_chunk_repo = AsyncMock()
        mock_langfuse = MagicMock()
        mock_langfuse.span.return_value = MagicMock()

        result = await retrieve_context(
            base_state,
            embedding_service_factory=_factory_with(mock_embedding_service),
            chunk_repository=mock_chunk_repo,
            db_session=AsyncMock(),
            langfuse=mock_langfuse,
        )

        # Outer handler converts the raised RuntimeError to an empty list
        # plus state["error"]; both are acceptable, but we want NO chunks.
        assert result["retrieved_chunks"] == []
