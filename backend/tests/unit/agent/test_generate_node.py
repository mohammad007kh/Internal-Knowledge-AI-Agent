# tests/unit/agent/test_generate_node.py
"""Unit tests for the generate_response LangGraph node.

The synthesizer is a LangChain ``BaseChatModel`` runnable so that
LangGraph's ``astream_events(version="v2")`` surfaces real
``on_chat_model_stream`` events to the SSE consumer in
:mod:`src.services.chat_stream_service`.  These tests inject a
:class:`FakeListChatModel` in place of :class:`ChatOpenAI` to keep the
suite hermetic.
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Same env-var preamble as the other backend unit tests — required before
# ``src.*`` imports load core.config.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    FakeListChatModel,
)
from langchain_core.messages import HumanMessage  # noqa: E402

from src.agent.nodes.generate import generate_response  # noqa: E402
from src.services.ai_model_resolver import AIModelClient  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_state():
    return {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "What is our refund policy?",
        "source_ids": ["src-1"],
        "retrieved_chunks": [
            {
                "chunk_id": "c1",
                "source_id": "src-1",
                "text": "Refunds within 30 days.",
                "score": 0.1,
            }
        ],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [HumanMessage(content="What is our refund policy?")],
        "final_answer": None,
        "error": None,
    }


@pytest.fixture()
def mock_langfuse():
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


def _resolver_for_client() -> AsyncMock:
    """Build a resolver that returns a stable :class:`AIModelClient`."""
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.2,
        max_tokens=1024,
        custom_prompt=None,
        capabilities={},
        http_client=MagicMock(),  # not used on the new code path
        api_key="sk-fake",
        base_url=None,
    )
    return resolver


def _factory_returning(model: Any):
    """Build a ``chat_model_factory`` that returns *model* for any client."""
    def _factory(_client: AIModelClient) -> Any:
        return model

    return _factory


# ---------------------------------------------------------------------------
# Happy path — final_answer set from streaming chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sets_final_answer(base_state, mock_langfuse):
    fake = FakeListChatModel(responses=["You can get a refund within 30 days."])
    resolver = _resolver_for_client()

    result = await generate_response(
        base_state,
        ai_model_resolver=resolver,
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake),
    )

    assert result["final_answer"] == "You can get a refund within 30 days."
    assert "error" not in result or result["error"] is None
    # The resolver must be queried with the seeded slot name "synthesizer"
    # so admin overrides on /admin/llm-settings actually apply.
    resolver.resolve.assert_awaited_once_with("synthesizer")


@pytest.mark.asyncio
async def test_span_emitted(base_state, mock_langfuse):
    fake = FakeListChatModel(responses=["ok"])
    await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake),
    )
    mock_langfuse.span.assert_called_once()
    span = mock_langfuse.span.return_value
    span.end.assert_called_once()


# ---------------------------------------------------------------------------
# Streaming surface — on_chat_model_stream events fire through callbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_on_chat_model_stream_events(base_state, mock_langfuse):
    """The chat model used by the node must emit ``on_chat_model_stream``.

    This is the "delta-stream contract" that
    :mod:`src.services.chat_stream_service` relies on — without it the
    frontend gets no live tokens and the synthetic tail-delta band-aid
    has to come back.

    We collect events from the chat model directly via
    ``astream_events(version="v2")`` — the same v2 API that
    ``CompiledStateGraph.astream_events`` uses.  If chunks fire here,
    they fire through LangGraph too because LangGraph re-emits the
    callbacks from any nested runnable.
    """
    fake = FakeListChatModel(responses=["Hello world"])
    kinds: set[str] = set()
    async for ev in fake.astream_events(
        [HumanMessage(content="hi")], version="v2"
    ):
        kinds.add(ev["event"])
    assert "on_chat_model_stream" in kinds, (
        f"FakeListChatModel must emit on_chat_model_stream events to be a "
        f"valid stand-in for ChatOpenAI(streaming=True); got kinds={kinds!r}"
    )

    # Sanity: the node consumes the stream and returns the concatenation.
    fake2 = FakeListChatModel(responses=["Hello world"])
    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake2),
    )
    assert result["final_answer"] == "Hello world"


@pytest.mark.asyncio
async def test_run_name_is_synthesizer(base_state, mock_langfuse):
    """The chat model must be tagged ``run_name="synthesizer"``.

    Langfuse spans, admin slot overrides, and SSE consumers all key off
    this name — drift here is silent and breaks observability.
    """
    captured: dict[str, Any] = {}

    class _CapturingFake(FakeListChatModel):
        def with_config(self, config=None, **kwargs):  # type: ignore[override]
            if isinstance(config, dict):
                captured.update(config)
            return super().with_config(config, **kwargs)

    fake = _CapturingFake(responses=["ok"])
    await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake),
    )

    assert captured.get("run_name") == "synthesizer"
    assert "synthesizer" in (captured.get("tags") or [])


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_returns_fallback(base_state, mock_langfuse):
    """Any exception out of the chat model is converted to the fallback message."""
    fake = FakeListChatModel(
        responses=["doesn't matter"],
        error_on_chunk_number=0,  # raise on the first chunk
    )
    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake),
    )
    assert result["error"] == "generation_failed"
    assert "knowledge base" in result["final_answer"]


@pytest.mark.asyncio
async def test_no_context_uses_fallback_message(base_state, mock_langfuse):
    """With no retrieved chunks the LLM is still called.

    The empty-context fallback text is injected into the system prompt by
    :func:`render_system_prompt` — the node itself doesn't short-circuit.
    """
    base_state["retrieved_chunks"] = []
    fake = FakeListChatModel(responses=["I don't have that information."])
    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(fake),
    )
    assert result.get("final_answer") == "I don't have that information."


# ---------------------------------------------------------------------------
# FX3 — retry-once-emitted guard
# ---------------------------------------------------------------------------
#
# Streaming retry is poison: once even one token has gone over the SSE wire
# we cannot tell tenacity to "rewind" the consumer's view, so a replay would
# duplicate output. The node guards this with a closure flag flipped on the
# first emitted chunk + a custom retry_predicate that returns False when
# the flag is set. These two tests pin both halves of that contract.
# ---------------------------------------------------------------------------


class _StreamingChatModelStub:
    """Hand-rolled chat-model stand-in with per-attempt scripts.

    ``with_config`` is a no-op (returns ``self``) so the retry-decorated
    ``_call`` invokes ``astream`` directly. Each call to ``astream`` runs
    the next entry in ``scripts`` — a callable that's an ``async def``
    producing chunks (and optionally raising). ``astream_calls`` counts
    invocations so tests can assert "exactly 1" or "exactly 2".
    """

    def __init__(self, scripts):  # noqa: ANN001
        self._scripts = list(scripts)
        self._idx = 0
        self.astream_calls = 0

    def with_config(self, config=None, **kwargs):  # noqa: ANN001, ANN003
        return self

    def astream(self, messages):  # noqa: ANN001 — matches BaseChatModel.astream
        self.astream_calls += 1
        if self._idx >= len(self._scripts):
            # Exhausted — every reasonable test sets enough scripts up
            # front, so this is a hard failure.
            raise AssertionError(
                f"astream called {self.astream_calls}x but only "
                f"{len(self._scripts)} scripts were provided",
            )
        script = self._scripts[self._idx]
        self._idx += 1
        return script()


def _make_api_status_error() -> Exception:
    """Construct a real :class:`openai.APIStatusError` instance.

    The retry predicate uses ``isinstance`` against the openai exception
    classes, so we MUST surface the real type — a generic ``Exception``
    would short-circuit the predicate's ``isinstance`` to False and
    silently mask a regression.
    """
    import httpx
    from openai import APIStatusError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=500, request=request)
    return APIStatusError("server error", response=response, body=None)


def _make_api_timeout_error() -> Exception:
    """Construct a real :class:`openai.APITimeoutError` instance."""
    import httpx
    from openai import APITimeoutError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return APITimeoutError(request=request)


@pytest.mark.asyncio
async def test_retry_disabled_after_first_chunk_emitted(base_state, mock_langfuse):
    """Once a chunk has been emitted, retry MUST NOT replay.

    Script: yield 3 tokens, then raise APIStatusError. tenacity's predicate
    must see ``chunks_emitted==True`` and refuse the retry, so ``astream``
    is invoked exactly once. The node returns the fallback message + the
    ``generation_failed`` error sentinel — a partial answer is unsafe to
    surface as a "successful" final_answer because the SSE consumer has
    already forwarded the partial output.
    """
    from langchain_core.messages import AIMessageChunk

    async def _yield_three_then_raise():
        yield AIMessageChunk(content="hel")
        yield AIMessageChunk(content="lo ")
        yield AIMessageChunk(content="wor")
        raise _make_api_status_error()

    stub = _StreamingChatModelStub(scripts=[_yield_three_then_raise])

    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(stub),
    )

    # The critical assertion: NO retry after a chunk was emitted.
    assert stub.astream_calls == 1, (
        f"streaming retry replayed {stub.astream_calls}x — must be 1 once "
        f"any chunk has been emitted, otherwise the SSE consumer sees "
        f"duplicated tokens"
    )
    # The node converts the post-emission failure to the empty-context
    # fallback and stamps the error sentinel.
    from src.agent.prompts import NO_CONTEXT_MESSAGE

    assert result["final_answer"] == NO_CONTEXT_MESSAGE
    assert result["error"] == "generation_failed"


@pytest.mark.asyncio
async def test_retry_still_works_for_pre_stream_failure(base_state, mock_langfuse):
    """A failure BEFORE any chunk is yielded must still retry.

    Script: attempt 1 raises ``APITimeoutError`` before yielding anything;
    attempt 2 yields the real answer. ``astream`` must therefore be
    invoked exactly twice and the final answer must be the success path.
    """
    from langchain_core.messages import AIMessageChunk

    async def _raise_timeout_pre_stream():
        # ``yield`` is needed for python to recognise this as an async
        # generator. We raise before ever yielding, so the consumer sees
        # zero chunks emitted on this attempt.
        if False:  # pragma: no cover — keeps the def an async generator
            yield AIMessageChunk(content="")
        raise _make_api_timeout_error()

    async def _yield_full_answer():
        yield AIMessageChunk(content="The ")
        yield AIMessageChunk(content="answer.")

    stub = _StreamingChatModelStub(
        scripts=[_raise_timeout_pre_stream, _yield_full_answer],
    )

    result = await generate_response(
        base_state,
        ai_model_resolver=_resolver_for_client(),
        langfuse=mock_langfuse,
        chat_model_factory=_factory_returning(stub),
    )

    assert stub.astream_calls == 2, (
        f"pre-stream failure must retry exactly once — got "
        f"{stub.astream_calls} astream invocations"
    )
    assert result["final_answer"] == "The answer."
    # Success path leaves ``error`` either absent or None.
    assert result.get("error") is None
