"""Unit tests for the reflector LangGraph node."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.reflector import reflect
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


def _state(*, retries: int = 0, answer: str = "Hello world", chunks: list | None = None) -> dict:
    return {
        "query": "What is the policy?",
        "final_answer": answer,
        "retrieved_chunks": list(chunks or []),
        "trace_id": "trace-1",
        "session_id": "sess-1",
        "user_id": "user-1",
        "reflector_retries": retries,
    }


def _langfuse() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


@pytest.mark.asyncio
async def test_satisfied_no_retry() -> None:
    resolver = _resolver_for(_openai_returning({"satisfied": True, "issues": []}))
    result = await reflect(
        _state(),
        ai_model_resolver=resolver,
        langfuse=_langfuse(),
        max_retries=1,
    )
    resolver.resolve.assert_awaited_once_with("reflector")
    assert result == {"reflector_feedback": None}


@pytest.mark.asyncio
async def test_unsatisfied_within_budget_requests_retry() -> None:
    resolver = _resolver_for(
        _openai_returning({"satisfied": False, "issues": ["missing X", "vague Y"]})
    )
    result = await reflect(
        _state(retries=0),
        ai_model_resolver=resolver,
        langfuse=_langfuse(),
        max_retries=1,
    )
    assert result["reflector_retries"] == 1
    assert "missing X" in result["reflector_feedback"]


@pytest.mark.asyncio
async def test_retry_budget_exhausted_terminates() -> None:
    resolver = _resolver_for(_openai_returning({"satisfied": False, "issues": ["x"]}))
    result = await reflect(
        _state(retries=1),
        ai_model_resolver=resolver,
        langfuse=_langfuse(),
        max_retries=1,
    )
    assert result == {"reflector_feedback": None}


@pytest.mark.asyncio
async def test_llm_error_treated_as_satisfied() -> None:
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    resolver = _resolver_for(failing)
    result = await reflect(
        _state(),
        ai_model_resolver=resolver,
        langfuse=_langfuse(),
        max_retries=1,
    )
    assert result == {"reflector_feedback": None}


@pytest.mark.asyncio
async def test_empty_answer_is_noop() -> None:
    resolver = _resolver_for(_openai_returning({"satisfied": True, "issues": []}))
    result = await reflect(
        _state(answer=""),
        ai_model_resolver=resolver,
        langfuse=_langfuse(),
        max_retries=1,
    )
    assert result == {}
    resolver.resolve.assert_not_called()
