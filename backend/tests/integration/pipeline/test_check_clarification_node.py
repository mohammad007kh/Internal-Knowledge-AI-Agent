"""Integration tests for check_clarification node."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from src.agent.nodes.clarify import check_clarification
from src.agent.state import AgentState


def _make_state(
    query: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentState:
    return {
        "messages": [HumanMessage(content=query)],
        "source_ids": [str(uuid.uuid4())],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": session_id or str(uuid.uuid4()),
        "user_id": user_id or str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "query": query,
        "final_answer": None,
        "error": None,
    }


async def test_unambiguous_query_does_not_require_clarification(
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state(
        "What is the comprehensive parental leave policy for full-time employees?"
    )
    result = await check_clarification(state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


async def test_short_query_requires_clarification(
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state("ok")  # len("ok") < 5
    result = await check_clarification(state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert result["clarification_question"] is not None


async def test_ambiguous_single_word_requires_clarification(
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state("what")  # single word in _AMBIGUOUS_SINGLE_WORDS
    result = await check_clarification(state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert "what" in result["clarification_question"].lower()
