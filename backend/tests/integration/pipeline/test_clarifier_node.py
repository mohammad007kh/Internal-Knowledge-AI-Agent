"""Integration tests for handle_clarification node."""
from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage

from src.agent.nodes.clarify import handle_clarification
from src.agent.state import AgentState


def _make_state(
    requires_clarification: bool = True,
    question: str | None = None,
) -> AgentState:
    return {
        "messages": [HumanMessage(content="hi")],
        "source_ids": [str(uuid.uuid4())],
        "retrieved_chunks": [],
        "requires_clarification": requires_clarification,
        "clarification_question": question,
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "query": "hi",
        "final_answer": None,
        "error": None,
    }


async def test_handle_clarification_returns_question_as_final_answer() -> None:
    """The clarification question is returned as the terminal answer."""
    q = "What specifically would you like to know?"
    state = _make_state(requires_clarification=True, question=q)
    result = await handle_clarification(state)
    assert result == {"final_answer": q, "sources": []}


async def test_handle_clarification_uses_default_when_no_question() -> None:
    """Falls back to a non-empty generic question when clarification_question is None."""
    state = _make_state(requires_clarification=True, question=None)
    result = await handle_clarification(state)
    assert isinstance(result["final_answer"], str)
    assert len(result["final_answer"]) > 0
    assert result["sources"] == []
