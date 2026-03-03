"""Integration tests for generate_response node."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage

from src.agent.nodes.generate import generate_response
from src.agent.state import AgentState


def _make_state(retrieved_chunks: list | None = None) -> AgentState:
    return {
        "messages": [HumanMessage(content="What is the parental leave policy?")],
        "source_ids": [str(uuid.uuid4())],
        "retrieved_chunks": retrieved_chunks
        or [
            {
                "chunk_id": str(uuid.uuid4()),
                "source_id": str(uuid.uuid4()),
                "text": "Employees get 12 weeks.",
                "score": 0.9,
            }
        ],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "query": "What is the parental leave policy?",
        "final_answer": None,
        "error": None,
    }


async def test_llm_response_stored_as_final_answer(
    mock_openai_client: AsyncMock,
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state()
    result = await generate_response(
        state, openai_client=mock_openai_client, langfuse=mock_langfuse
    )
    assert result["final_answer"] == "The parental leave policy provides 12 weeks."


async def test_anti_fabrication_instruction_in_system_prompt(
    mock_openai_client: AsyncMock,
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state()
    await generate_response(
        state, openai_client=mock_openai_client, langfuse=mock_langfuse
    )
    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "ONLY" in system_content


async def test_llm_failure_sets_error_state(mock_langfuse: MagicMock) -> None:
    bad_client = AsyncMock()
    bad_client.chat.completions.create = AsyncMock(
        side_effect=Exception("OpenAI unavailable")
    )
    state = _make_state()
    result = await generate_response(
        state, openai_client=bad_client, langfuse=mock_langfuse
    )
    assert result["error"] == "generation_failed"
    assert result["final_answer"] is not None  # returns NO_CONTEXT_MESSAGE
