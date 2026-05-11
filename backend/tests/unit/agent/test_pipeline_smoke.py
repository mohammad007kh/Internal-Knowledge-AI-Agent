"""Smoke test: full pipeline with all external deps mocked."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.agent.pipeline import build_pipeline, run_pipeline
from src.services.ai_model_resolver import AIModelClient


@pytest.fixture()
def mocked_pipeline(monkeypatch: pytest.MonkeyPatch):
    # The synthesizer node (FX3) builds a LangChain ``ChatOpenAI`` via
    # ``build_chat_model``; in tests there's no API key, so swap in a fake
    # streaming chat model. ``generate_response`` resolves the factory at
    # call time, so patching the name it imports is enough — the pipeline
    # graph calls the node without passing ``chat_model_factory``.
    monkeypatch.setattr(
        "src.agent.nodes.generate.build_chat_model",
        lambda _client: FakeListChatModel(responses=["Here is the answer."]),
    )

    mock_db = AsyncMock()

    mock_embedding = AsyncMock()
    mock_embedding.embed_query.return_value = [0.1] * 1536
    mock_embedding.embed_texts.return_value = [[0.1] * 1536]

    mock_factory = AsyncMock()
    # ``for_active`` now returns ``(service, embedder_id)``.
    mock_factory.for_active.return_value = (mock_embedding, uuid.uuid4())

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.similarity_search.return_value = []

    mock_chat_session_repo = AsyncMock()
    mock_session = MagicMock()
    mock_session.user_id = "user-1"
    mock_chat_session_repo.get.return_value = mock_session

    mock_chat_msg_repo = AsyncMock()
    mock_chat_msg_repo.list_for_session.return_value = []
    mock_chat_msg_repo.create.return_value = MagicMock()

    mock_openai = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "Here is the answer."
    completion.usage.prompt_tokens = 50
    completion.usage.completion_tokens = 10
    mock_openai.chat.completions.create.return_value = completion

    mock_resolver = AsyncMock()
    mock_resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.2,
        max_tokens=1024,
        custom_prompt=None,
        capabilities={},
        http_client=mock_openai,
    )

    mock_langfuse = MagicMock()
    mock_span = MagicMock()
    mock_langfuse.span.return_value = mock_span

    return build_pipeline(
        db_session=mock_db,
        chunk_repository=mock_chunk_repo,
        chat_session_repository=mock_chat_session_repo,
        chat_message_repository=mock_chat_msg_repo,
        ai_model_resolver=mock_resolver,
        embedding_service_factory=mock_factory,
        langfuse=mock_langfuse,
    )


@pytest.mark.asyncio
async def test_pipeline_returns_final_answer(mocked_pipeline):
    result = await run_pipeline(
        compiled_graph=mocked_pipeline,
        session_id="00000000-0000-0000-0000-000000000001",
        user_id="user-1",
        query="What is the return policy?",
        source_ids=["src-1"],
        trace_id="trace-1",
    )
    assert result["final_answer"] == "Here is the answer."
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_pipeline_short_query_triggers_clarification(mocked_pipeline):
    result = await run_pipeline(
        compiled_graph=mocked_pipeline,
        session_id="00000000-0000-0000-0000-000000000002",
        user_id="user-1",
        query="hi",
        source_ids=["src-1"],
        trace_id="trace-2",
    )
    assert result.get("requires_clarification") is True
