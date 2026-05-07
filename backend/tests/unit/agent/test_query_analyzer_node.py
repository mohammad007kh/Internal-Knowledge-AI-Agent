"""Unit tests for the query_analyzer LangGraph node."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.query_analyzer import analyze_query
from src.services.ai_model_resolver import AIModelClient


def _resolver_for(http_client) -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.3,
        max_tokens=1024,
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


def _state(query: str = "What is the refund policy?") -> dict:
    return {
        "query": query,
        "trace_id": "trace-1",
        "session_id": "sess-1",
        "user_id": "user-1",
    }


def _langfuse() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


@pytest.mark.asyncio
async def test_returns_three_variants_from_llm() -> None:
    payload = {
        "variants": [
            "What is the refund policy?",
            "Refund timeline rules",
            "How long does a refund take?",
        ]
    }
    resolver = _resolver_for(_openai_returning(payload))
    result = await analyze_query(_state(), ai_model_resolver=resolver, langfuse=_langfuse())
    # Slot must be the EXACT seeded name.
    resolver.resolve.assert_awaited_once_with("query_analyzer")
    assert result["query_variants"] == payload["variants"]


@pytest.mark.asyncio
async def test_inserts_original_query_when_missing() -> None:
    payload = {"variants": ["Refund timeline rules", "How long for a refund?"]}
    resolver = _resolver_for(_openai_returning(payload))
    result = await analyze_query(_state(), ai_model_resolver=resolver, langfuse=_langfuse())
    variants = result["query_variants"]
    assert variants[0] == "What is the refund policy?"
    assert len(variants) <= 3


@pytest.mark.asyncio
async def test_falls_back_to_single_variant_on_llm_error() -> None:
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    resolver = _resolver_for(failing)
    result = await analyze_query(_state(), ai_model_resolver=resolver, langfuse=_langfuse())
    assert result["query_variants"] == ["What is the refund policy?"]


@pytest.mark.asyncio
async def test_falls_back_on_invalid_json() -> None:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "not-json"
    client.chat.completions.create.return_value = completion
    resolver = _resolver_for(client)
    result = await analyze_query(_state(), ai_model_resolver=resolver, langfuse=_langfuse())
    assert result["query_variants"] == ["What is the refund policy?"]


@pytest.mark.asyncio
async def test_empty_query_returns_empty_variants() -> None:
    resolver = _resolver_for(_openai_returning({"variants": ["x"]}))
    result = await analyze_query(_state(query="   "), ai_model_resolver=resolver, langfuse=_langfuse())
    assert result["query_variants"] == []
    resolver.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_reflector_feedback_fed_back_into_llm_prompt() -> None:
    """Slice E defect-2 fix: reflector retry must surface feedback to the LLM.

    Without this, the second pass through query_analyzer re-runs the same
    prompt with the same query, so the retry loop is theatre.
    """
    http_client = _openai_returning({"variants": ["refund timeline rules"]})
    resolver = _resolver_for(http_client)
    state = _state()
    state["reflector_feedback"] = "Answer omitted the 14-day window."
    await analyze_query(state, ai_model_resolver=resolver, langfuse=_langfuse())

    # Inspect the actual messages sent to the LLM.
    kwargs = http_client.chat.completions.create.await_args.kwargs
    user_msg = next(m for m in kwargs["messages"] if m["role"] == "user")
    assert "Previous attempt was rejected" in user_msg["content"]
    assert "14-day window" in user_msg["content"]
    # Original query is still present.
    assert "What is the refund policy?" in user_msg["content"]


@pytest.mark.asyncio
async def test_no_reflector_feedback_keeps_prompt_clean() -> None:
    """Without feedback, the user message has the query under the LATEST
    USER MESSAGE label and no retry preamble."""
    http_client = _openai_returning({"variants": ["v1"]})
    resolver = _resolver_for(http_client)
    await analyze_query(_state(), ai_model_resolver=resolver, langfuse=_langfuse())

    kwargs = http_client.chat.completions.create.await_args.kwargs
    user_msg = next(m for m in kwargs["messages"] if m["role"] == "user")
    # The query is now wrapped in a labelled section so the rewriter knows
    # which line to act on; "rejected because" preamble must be absent.
    assert "LATEST USER MESSAGE:" in user_msg["content"]
    assert "What is the refund policy?" in user_msg["content"]
    assert "rejected because" not in user_msg["content"]
