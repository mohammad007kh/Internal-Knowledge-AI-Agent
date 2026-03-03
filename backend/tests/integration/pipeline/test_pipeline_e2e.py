"""End-to-end pipeline integration tests using build_pipeline."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from src.agent.pipeline import build_pipeline, run_pipeline


def _make_deps(user_id: str) -> dict:
    mock_langfuse = MagicMock()

    choice = MagicMock()
    choice.message.content = "The parental leave policy provides 12 weeks of paid leave."
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    mock_openai = AsyncMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=response)

    mock_embed = AsyncMock()
    mock_embed.embed_texts.return_value = [[0.1] * 1536]

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.similarity_search.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "source_id": str(uuid.uuid4()),
            "text": "12 weeks parental leave.",
            "score": 0.95,
        }
    ]

    session_obj = MagicMock()
    session_obj.user_id = user_id
    mock_session_repo = AsyncMock()
    mock_session_repo.get.return_value = session_obj

    mock_msg_repo = AsyncMock()
    mock_msg_repo.list_for_session.return_value = []
    mock_msg_repo.create = AsyncMock()

    mock_db = AsyncMock()

    return {
        "db_session": mock_db,
        "embedding_service": mock_embed,
        "chunk_repository": mock_chunk_repo,
        "chat_session_repository": mock_session_repo,
        "chat_message_repository": mock_msg_repo,
        "openai_client": mock_openai,
        "langfuse": mock_langfuse,
    }


async def test_unambiguous_query_completes_with_answer() -> None:
    uid = str(uuid.uuid4())
    deps = _make_deps(user_id=uid)
    pipeline = build_pipeline(**deps)
    result = await run_pipeline(
        compiled_graph=pipeline,
        session_id=str(uuid.uuid4()),
        user_id=uid,
        query="What is the comprehensive parental leave policy for full-time staff?",
        source_ids=[str(uuid.uuid4())],
        trace_id=str(uuid.uuid4()),
    )
    assert result["final_answer"] is not None
    assert result["error"] is None


async def test_langfuse_spans_emitted_during_pipeline() -> None:
    uid = str(uuid.uuid4())
    deps = _make_deps(user_id=uid)
    pipeline = build_pipeline(**deps)
    await run_pipeline(
        compiled_graph=pipeline,
        session_id=str(uuid.uuid4()),
        user_id=uid,
        query="Describe the employee benefits package comprehensively.",
        source_ids=[str(uuid.uuid4())],
        trace_id=str(uuid.uuid4()),
    )
    assert deps["langfuse"].span.called


async def test_messages_persisted_after_pipeline() -> None:
    uid = str(uuid.uuid4())
    deps = _make_deps(user_id=uid)
    pipeline = build_pipeline(**deps)
    await run_pipeline(
        compiled_graph=pipeline,
        session_id=str(uuid.uuid4()),
        user_id=uid,
        query="What vacation days are employees entitled to receive annually?",
        source_ids=[str(uuid.uuid4())],
        trace_id=str(uuid.uuid4()),
    )
    assert deps["chat_message_repository"].create.call_count == 2
