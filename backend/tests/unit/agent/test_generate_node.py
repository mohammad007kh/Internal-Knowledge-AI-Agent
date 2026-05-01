# tests/unit/agent/test_generate_node.py
"""Unit tests for the generate_response LangGraph node."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from src.agent.nodes.generate import generate_response
from src.services.ai_model_resolver import AIModelClient


@pytest.fixture()
def base_state():
    return {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "What is our refund policy?",
        "source_ids": ["src-1"],
        "retrieved_chunks": [
            {"chunk_id": "c1", "source_id": "src-1", "text": "Refunds within 30 days.", "score": 0.1}
        ],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [HumanMessage(content="What is our refund policy?")],
        "final_answer": None,
        "error": None,
    }


@pytest.fixture()
def mock_openai_client():
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "You can get a refund within 30 days."
    completion.usage.prompt_tokens = 100
    completion.usage.completion_tokens = 25
    client.chat.completions.create.return_value = completion
    return client


@pytest.fixture()
def mock_langfuse():
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


def _resolver_for(http_client) -> AsyncMock:
    """Build a resolver that returns an :class:`AIModelClient` wrapping *http_client*."""
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.2,
        max_tokens=1024,
        custom_prompt=None,
        capabilities={},
        http_client=http_client,
    )
    return resolver


@pytest.mark.asyncio
async def test_sets_final_answer(base_state, mock_openai_client, mock_langfuse):
    resolver = _resolver_for(mock_openai_client)
    result = await generate_response(
        base_state,
        ai_model_resolver=resolver,
        langfuse=mock_langfuse,
    )
    assert result["final_answer"] == "You can get a refund within 30 days."
    assert "error" not in result or result["error"] is None
    # A.1 — resolver must be queried with the seeded slot name "synthesizer"
    # so admin overrides on /admin/llm-settings actually apply.
    resolver.resolve.assert_awaited_once_with("synthesizer")


@pytest.mark.asyncio
async def test_span_emitted(base_state, mock_openai_client, mock_langfuse):
    await generate_response(
        base_state,
        ai_model_resolver=_resolver_for(mock_openai_client),
        langfuse=mock_langfuse,
    )
    mock_langfuse.span.assert_called_once()
    span = mock_langfuse.span.return_value
    span.end.assert_called_once()


@pytest.mark.asyncio
async def test_openai_failure_returns_fallback(base_state, mock_langfuse):
    from openai import APIStatusError  # noqa: PLC0415

    failing_client = AsyncMock()
    failing_client.chat.completions.create.side_effect = APIStatusError(
        "rate limit", response=MagicMock(status_code=429), body={}
    )

    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for(failing_client),
        langfuse=mock_langfuse,
    )
    assert result["error"] == "generation_failed"
    assert "knowledge base" in result["final_answer"]


@pytest.mark.asyncio
async def test_no_context_uses_fallback_message(base_state, mock_openai_client, mock_langfuse):
    """With no retrieved chunks still calls LLM — fallback text injected into prompt."""
    base_state["retrieved_chunks"] = []
    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for(mock_openai_client),
        langfuse=mock_langfuse,
    )
    assert mock_openai_client.chat.completions.create.called
    assert result.get("final_answer") is not None
