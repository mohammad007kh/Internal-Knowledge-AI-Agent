"""Integration tests for handle_clarification node."""
from __future__ import annotations

import uuid
from unittest.mock import patch

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


async def test_handle_clarification_calls_interrupt_with_question() -> None:
    """interrupt() is invoked with the clarification question from state."""
    q = "What specifically would you like to know?"
    state = _make_state(requires_clarification=True, question=q)
    with patch("src.agent.nodes.clarify.interrupt") as mock_interrupt:
        mock_interrupt.return_value = "I want to know about parental leave."
        result = await handle_clarification(state)
    mock_interrupt.assert_called_once_with(q)
    assert result["query"] == "I want to know about parental leave."
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


async def test_handle_clarification_uses_default_when_no_question() -> None:
    """Falls back to a non-empty generic question when clarification_question is None."""
    state = _make_state(requires_clarification=True, question=None)
    with patch("src.agent.nodes.clarify.interrupt") as mock_interrupt:
        mock_interrupt.return_value = "More context here."
        await handle_clarification(state)
    called_with: str = mock_interrupt.call_args[0][0]
    assert len(called_with) > 0
