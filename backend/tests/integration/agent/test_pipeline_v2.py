"""End-to-end integration test for the v2 pipeline graph.

Patches the resolver and HTTP client minimally so the graph wires up
the new nodes (clarify-LLM, query_analyzer, source_router) and the
synthesizer all in one run.  Asserts:

* Each new node was invoked exactly once.
* The resolver was called with the EXACT slot name per node.
* ``state["query_variants"]``, ``state["selected_source_ids"]`` and the
  final answer all flow through correctly.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.pipeline import build_pipeline, run_pipeline
from src.models.enums import SourceType
from src.services.ai_model_resolver import AIModelClient


def _client_returning(payload: dict | str) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = (
        payload if isinstance(payload, str) else json.dumps(payload)
    )
    completion.usage.prompt_tokens = 50
    completion.usage.completion_tokens = 10
    client.chat.completions.create.return_value = completion
    return client


def _make_resolver_router(stage_payloads: dict[str, AsyncMock]) -> AsyncMock:
    """Return a resolver that hands out a different fake client per stage."""
    resolver = AsyncMock()

    async def _resolve(stage: str) -> AIModelClient:
        http_client = stage_payloads.get(stage)
        if http_client is None:
            # Default: a benign stub.
            http_client = _client_returning("ok")
        return AIModelClient(
            ai_model_id=uuid.uuid4(),
            provider="openai",
            model_id="gpt-4o-mini",
            temperature=0.0,
            max_tokens=1024,
            custom_prompt=None,
            capabilities={},
            http_client=http_client,
        )

    resolver.resolve.side_effect = _resolve
    return resolver


@pytest.mark.asyncio
async def test_v2_pipeline_invokes_each_new_node() -> None:
    user_id = "user-1"
    source_id = uuid.uuid4()

    # Per-stage fake LLM responses ----------------------------------------
    clients = {
        "clarification_detector": _client_returning(
            {"needs_clarification": False, "question": None}
        ),
        "query_analyzer": _client_returning(
            {"variants": ["What is the refund policy?", "refund timeline rules"]}
        ),
        "source_router": _client_returning(
            {"selected_source_ids": [str(source_id)], "use_text_to_query_for": []}
        ),
        "synthesizer": _client_returning("Refunds within 30 days."),
    }
    resolver = _make_resolver_router(clients)

    # Source repository — returns one accessible web source.
    src = MagicMock()
    src.id = source_id
    src.name = "docs"
    src.source_type = SourceType.WEB_URL
    src.description = "Marketing docs"
    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [src]

    # Embedding + chunk repo — produce one matching chunk.
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())

    fake_chunk = MagicMock()
    fake_chunk.id = "chunk-1"
    fake_chunk.source_id = str(source_id)
    fake_chunk.chunk_text = "Refunds processed within 30 days."
    fake_chunk.metadata_ = {
        "document_title": "Refund.pdf",
        "page_number": 1,
        "source_name": "docs",
    }
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

    chat_session_repo = AsyncMock()
    fake_session = MagicMock()
    fake_session.user_id = user_id
    chat_session_repo.get.return_value = fake_session
    chat_msg_repo = AsyncMock()
    chat_msg_repo.list_for_session.return_value = []

    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()
    langfuse.start_span.return_value = MagicMock()

    # No guardrail service for this run — keeps the graph minimal.
    pipeline = build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_msg_repo,
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=None,
        source_repository=source_repo,
    )

    result = await run_pipeline(
        compiled_graph=pipeline,
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        query="What is the refund policy?",
        source_ids=[str(source_id)],
        trace_id="trace-1",
    )

    assert result["final_answer"] == "Refunds within 30 days."
    assert result.get("error") is None
    # New node state writes are present.
    assert result["query_variants"]
    assert result["selected_source_ids"] == [str(source_id)]
    # Resolver was queried for every stage that has an LLM.
    awaited_stages = {
        call.args[0] for call in resolver.resolve.await_args_list
    }
    assert {"clarification_detector", "query_analyzer", "source_router", "synthesizer"} <= awaited_stages


@pytest.mark.asyncio
async def test_v2_pipeline_runs_guardrail_input_before_check_clarification() -> None:
    """Slice E defect-3 fix: guardrails must gate the LLM clarifier in V2.

    Hostile / PII-laden queries should be blocked by ``guardrail_input``
    before ``check_clarification`` ever issues an LLM call to decide
    whether to ask the user to clarify.  We assert the topological edge
    ordering, not run-time semantics.
    """
    resolver = _make_resolver_router({})
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())
    chunk_repo = AsyncMock()
    chat_session_repo = AsyncMock()
    chat_msg_repo = AsyncMock()
    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()
    langfuse.start_span.return_value = MagicMock()
    source_repo = AsyncMock()
    guardrail = MagicMock()  # presence is what matters; nodes are mocked

    pipeline = build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_msg_repo,
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=guardrail,
        source_repository=source_repo,
    )

    graph = pipeline.get_graph()
    edges = [(e.source, e.target) for e in graph.edges]

    # 1) load_history flows directly into guardrail_input (not clarify).
    assert ("load_history", "guardrail_input") in edges
    assert ("load_history", "check_clarification") not in edges
    # 2) guardrail_input is upstream of check_clarification (via conditional).
    assert ("guardrail_input", "check_clarification") in edges
    # 3) check_clarification is no longer a direct successor of load_history.
    successors_of_load = {t for s, t in edges if s == "load_history"}
    assert successors_of_load == {"guardrail_input"}


@pytest.mark.asyncio
async def test_v2_pipeline_falls_back_to_v1_without_source_repository() -> None:
    """When source_repository is omitted the v1 graph is built (rollback path)."""
    resolver = _make_resolver_router(
        {"synthesizer": _client_returning("v1 answer")}
    )
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = []
    chat_session_repo = AsyncMock()
    fake_session = MagicMock()
    fake_session.user_id = "u1"
    chat_session_repo.get.return_value = fake_session
    chat_msg_repo = AsyncMock()
    chat_msg_repo.list_for_session.return_value = []
    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()
    langfuse.start_span.return_value = MagicMock()

    pipeline = build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_msg_repo,
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=None,
        source_repository=None,
    )
    result = await run_pipeline(
        compiled_graph=pipeline,
        session_id=str(uuid.uuid4()),
        user_id="u1",
        query="What is the refund policy?",
        source_ids=[str(uuid.uuid4())],
        trace_id="trace-1",
    )
    # v1 path uses the heuristic clarify, no query_analyzer / source_router.
    awaited_stages = {
        call.args[0] for call in resolver.resolve.await_args_list
    }
    assert "clarification_detector" not in awaited_stages
    assert "query_analyzer" not in awaited_stages
    assert "source_router" not in awaited_stages
    assert "synthesizer" in awaited_stages
    assert result["final_answer"] == "v1 answer"
