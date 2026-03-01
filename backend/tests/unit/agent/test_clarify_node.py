"""Unit tests for check_clarification and handle_clarification nodes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.clarify import check_clarification, handle_clarification


@pytest.fixture
def base_state() -> dict:  # type: ignore[type-arg]
    return {
        "trace_id": "trace-abc",
        "session_id": "sess-1",
        "query": "How do I reset my password?",
        "messages": [],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "response": None,
        "error": None,
    }


@pytest.fixture
def mock_langfuse() -> MagicMock:
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


@pytest.mark.asyncio
async def test_normal_query_no_clarification(
    base_state: dict,  # type: ignore[type-arg]
    mock_langfuse: MagicMock,
) -> None:
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


@pytest.mark.asyncio
async def test_short_query_requires_clarification(
    base_state: dict,  # type: ignore[type-arg]
    mock_langfuse: MagicMock,
) -> None:
    base_state["query"] = "hi"
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert result["clarification_question"]


@pytest.mark.asyncio
async def test_single_ambiguous_word_requires_clarification(
    base_state: dict,  # type: ignore[type-arg]
    mock_langfuse: MagicMock,
) -> None:
    base_state["query"] = "where"
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert "ambiguous" in result["clarification_question"].lower()


@pytest.mark.asyncio
async def test_span_emitted(
    base_state: dict,  # type: ignore[type-arg]
    mock_langfuse: MagicMock,
) -> None:
    await check_clarification(base_state, langfuse=mock_langfuse)
    mock_langfuse.span.assert_called_once_with(
        trace_id="trace-abc",
        name="check_clarification",
        input={"query": "How do I reset my password?"},
    )
    mock_langfuse.span.return_value.end.assert_called_once()


@pytest.mark.asyncio
async def test_handle_clarification_calls_interrupt(
    base_state: dict,  # type: ignore[type-arg]
) -> None:
    base_state["clarification_question"] = "Which product do you mean?"
    with patch(
        "src.agent.nodes.clarify.interrupt", return_value="I mean the Pro plan"
    ) as mock_interrupt:
        result = await handle_clarification(base_state)
    mock_interrupt.assert_called_once_with("Which product do you mean?")
    assert result["query"] == "I mean the Pro plan"
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None
    assert len(result["messages"]) == 1
