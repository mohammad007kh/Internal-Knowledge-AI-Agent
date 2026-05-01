"""Unit tests for check_clarification (heuristic + LLM) and handle_clarification."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.nodes.clarify import check_clarification, handle_clarification
from src.services.ai_model_resolver import AIModelClient


@pytest.fixture
def base_state() -> dict:
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


# ---------------------------------------------------------------------------
# Heuristic path (no resolver passed) — existing behaviour preserved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_query_no_clarification(base_state, mock_langfuse) -> None:
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


@pytest.mark.asyncio
async def test_short_query_requires_clarification(base_state, mock_langfuse) -> None:
    base_state["query"] = "hi"
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert result["clarification_question"]


@pytest.mark.asyncio
async def test_single_ambiguous_word_requires_clarification(base_state, mock_langfuse) -> None:
    base_state["query"] = "where"
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert "ambiguous" in result["clarification_question"].lower()


@pytest.mark.asyncio
async def test_span_emitted(base_state, mock_langfuse) -> None:
    await check_clarification(base_state, langfuse=mock_langfuse)
    mock_langfuse.span.assert_called_once_with(
        trace_id="trace-abc",
        name="check_clarification",
        input={"query": "How do I reset my password?"},
    )
    mock_langfuse.span.return_value.end.assert_called_once()


@pytest.mark.asyncio
async def test_handle_clarification_calls_interrupt(base_state) -> None:
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


# ---------------------------------------------------------------------------
# LLM path (v2 — resolver passed).
# ---------------------------------------------------------------------------


def _resolver_for(http_client) -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.0,
        max_tokens=512,
        custom_prompt=None,
        capabilities={},
        http_client=http_client,
    )
    return resolver


def _openai_returning(payload: dict) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    client.chat.completions.create.return_value = completion
    return client


@pytest.mark.asyncio
async def test_llm_says_needs_clarification(base_state, mock_langfuse) -> None:
    resolver = _resolver_for(
        _openai_returning(
            {"needs_clarification": True, "question": "Which product family?"}
        )
    )
    result = await check_clarification(
        base_state, langfuse=mock_langfuse, ai_model_resolver=resolver
    )
    resolver.resolve.assert_awaited_once_with("clarification_detector")
    assert result["requires_clarification"] is True
    assert result["clarification_question"] == "Which product family?"


@pytest.mark.asyncio
async def test_llm_says_no_clarification(base_state, mock_langfuse) -> None:
    resolver = _resolver_for(
        _openai_returning({"needs_clarification": False, "question": None})
    )
    result = await check_clarification(
        base_state, langfuse=mock_langfuse, ai_model_resolver=resolver
    )
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_heuristic(base_state, mock_langfuse) -> None:
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    resolver = _resolver_for(failing)

    base_state["query"] = "hi"  # heuristic flags this short query.
    result = await check_clarification(
        base_state, langfuse=mock_langfuse, ai_model_resolver=resolver
    )
    assert result["requires_clarification"] is True
    assert result["clarification_question"]
