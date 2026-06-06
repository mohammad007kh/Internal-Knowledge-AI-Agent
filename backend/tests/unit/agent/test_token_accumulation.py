# tests/unit/agent/test_token_accumulation.py
"""T-050: Token accumulation into additive state reducers.

Verifies:
- AgentState token fields are Annotated[int, operator.add]
- Each LLM-calling node (generate, source_router, clarify) returns token deltas
- Synthesizer records estimated_output_tokens in span input pre-call (estimate-then-reconcile)
- turn_token_cost Langfuse score emitted at generate_response return with accumulated total
- Simulated ≥3-node run sums correctly via manual operator.add application
"""
from __future__ import annotations

import operator
import os
import typing
import uuid
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402
from langchain_core.messages import AIMessageChunk, HumanMessage  # noqa: E402

from src.agent.nodes.clarify import check_clarification  # noqa: E402
from src.agent.nodes.generate import generate_response  # noqa: E402
from src.agent.nodes.source_router import route_sources  # noqa: E402
from src.agent.state import AgentState  # noqa: E402
from src.models.enums import SourceType  # noqa: E402
from src.services.ai_model_resolver import AIModelClient  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _base_state(**extra) -> dict:  # type: ignore[type-arg]
    return {
        "session_id": "sess-tok",
        "user_id": "user-tok",
        "trace_id": "trace-tok",
        "query": "How many orders are there?",
        "source_ids": [],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [HumanMessage(content="How many orders are there?")],
        "final_answer": None,
        "error": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        **extra,
    }


def _langfuse() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


def _resolver_for(http_client: MagicMock | None = None, max_tokens: int = 512) -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.0,
        max_tokens=max_tokens,
        custom_prompt=None,
        capabilities={},
        http_client=http_client or MagicMock(),
        api_key="sk-fake",
        base_url=None,
    )
    return resolver


def _openai_with_usage(payload: dict, in_tok: int = 30, out_tok: int = 15) -> AsyncMock:
    """Build an AsyncOpenAI mock that returns *payload* JSON and reports usage."""
    import json

    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    usage = MagicMock()
    usage.prompt_tokens = in_tok
    usage.completion_tokens = out_tok
    completion.usage = usage
    client.chat.completions.create.return_value = completion
    return client


# ---------------------------------------------------------------------------
# 1. AgentState: both token fields must be additive reducers
# ---------------------------------------------------------------------------


def test_token_fields_are_annotated_with_operator_add() -> None:
    """AgentState must declare both token fields as Annotated[int, operator.add]."""
    hints = typing.get_type_hints(AgentState, include_extras=True)
    for field in ("total_input_tokens", "total_output_tokens"):
        hint = hints[field]
        assert hasattr(hint, "__metadata__"), (
            f"{field} must be Annotated[int, operator.add]; got {hint!r}"
        )
        assert hint.__metadata__[0] is operator.add, (
            f"{field} reducer must be operator.add; got {hint.__metadata__[0]!r}"
        )


def test_operator_add_accumulates_correctly() -> None:
    """Manual reducer simulation: three node deltas sum to the expected total."""
    acc_in = acc_out = 0
    for n_in, n_out in [(10, 5), (20, 10), (30, 15)]:
        acc_in = operator.add(acc_in, n_in)
        acc_out = operator.add(acc_out, n_out)
    assert acc_in == 60
    assert acc_out == 30


# ---------------------------------------------------------------------------
# 2. generate_response: returns token deltas + emits turn_token_cost score
# ---------------------------------------------------------------------------


class _UsageStreamModel:
    """Fake streaming model that emits text chunks then a usage_metadata final chunk."""

    def __init__(self, text: str, in_tok: int = 50, out_tok: int = 25) -> None:
        self._text = text
        self._in_tok = in_tok
        self._out_tok = out_tok

    def with_config(self, config=None, **kwargs):  # type: ignore[no-untyped-def]
        return self

    def astream(self, messages):  # type: ignore[no-untyped-def]
        in_tok, out_tok = self._in_tok, self._out_tok

        async def _gen():  # type: ignore[return]
            for word in self._text.split():
                yield AIMessageChunk(content=word + " ")
            yield AIMessageChunk(
                content="",
                usage_metadata={"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok},
            )

        return _gen()


@pytest.mark.asyncio
async def test_generate_returns_token_deltas() -> None:
    """generate_response must include total_input_tokens / total_output_tokens in its return dict."""
    model = _UsageStreamModel("The answer is 42.", in_tok=80, out_tok=40)
    result = await generate_response(
        _base_state(),
        ai_model_resolver=_resolver_for(),
        langfuse=_langfuse(),
        chat_model_factory=lambda _c: model,
    )
    assert result["total_input_tokens"] == 80
    assert result["total_output_tokens"] == 40


@pytest.mark.asyncio
async def test_generate_emits_turn_token_cost_score() -> None:
    """generate_response must emit a turn_token_cost Langfuse score at turn end.

    The score value must equal (prior accumulated tokens) + (this node's delta).
    """
    model = _UsageStreamModel("ok", in_tok=60, out_tok=20)
    lf = _langfuse()
    # Simulate prior nodes having already accumulated 100 in + 50 out
    state = _base_state(total_input_tokens=100, total_output_tokens=50)
    await generate_response(
        state,
        ai_model_resolver=_resolver_for(),
        langfuse=lf,
        chat_model_factory=lambda _c: model,
    )
    lf.score.assert_called_once()
    kwargs = lf.score.call_args.kwargs
    assert kwargs["name"] == "turn_token_cost"
    # 100 + 50 (prior) + 60 + 20 (this node) = 230
    assert kwargs["value"] == pytest.approx(230.0)
    assert kwargs["trace_id"] == "trace-tok"


@pytest.mark.asyncio
async def test_generate_returns_zero_deltas_on_failure() -> None:
    """On LLM failure, generate_response must still return 0/0 token deltas."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    fake = FakeListChatModel(responses=["x"], error_on_chunk_number=0)
    result = await generate_response(
        _base_state(),
        ai_model_resolver=_resolver_for(),
        langfuse=_langfuse(),
        chat_model_factory=lambda _c: fake,
    )
    assert result.get("total_input_tokens", 0) == 0
    assert result.get("total_output_tokens", 0) == 0


@pytest.mark.asyncio
async def test_generate_synthesizer_estimate_in_span_input() -> None:
    """Span input must contain estimated_output_tokens = client.max_tokens (pre-call estimate)."""
    model = _UsageStreamModel("answer", in_tok=40, out_tok=20)
    lf = _langfuse()
    max_tok = 768
    await generate_response(
        _base_state(),
        ai_model_resolver=_resolver_for(max_tokens=max_tok),
        langfuse=lf,
        chat_model_factory=lambda _c: model,
    )
    span_call_kwargs = lf.span.call_args.kwargs or {}
    span_input = span_call_kwargs.get("input", {})
    assert span_input.get("estimated_output_tokens") == max_tok, (
        "Span input must record estimated_output_tokens = client.max_tokens "
        "for the pre-call budget snapshot (estimate-then-reconcile)"
    )


# ---------------------------------------------------------------------------
# 3. route_sources: returns token deltas
# ---------------------------------------------------------------------------


def _source(*, type_: SourceType = SourceType.WEB_URL) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.name = "src"
    s.source_type = type_
    s.description = "desc"
    return s


@pytest.mark.asyncio
async def test_route_sources_returns_token_deltas() -> None:
    s = _source()
    payload = {"selected_source_ids": [str(s.id)], "use_text_to_query_for": []}
    http = _openai_with_usage(payload, in_tok=40, out_tok=10)
    repo = AsyncMock()
    repo.list_by_ids.return_value = [s]

    result = await route_sources(
        _base_state(source_ids=[str(s.id)]),
        ai_model_resolver=_resolver_for(http),
        db_session=AsyncMock(),
        source_repository=repo,
        langfuse=_langfuse(),
    )
    assert result["total_input_tokens"] == 40
    assert result["total_output_tokens"] == 10


@pytest.mark.asyncio
async def test_route_sources_zero_deltas_on_llm_error() -> None:
    """LLM error → fallback to all-accessible; token deltas must be 0/0."""
    s = _source()
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    repo = AsyncMock()
    repo.list_by_ids.return_value = [s]

    result = await route_sources(
        _base_state(source_ids=[str(s.id)]),
        ai_model_resolver=_resolver_for(failing),
        db_session=AsyncMock(),
        source_repository=repo,
        langfuse=_langfuse(),
    )
    assert result.get("total_input_tokens", 0) == 0
    assert result.get("total_output_tokens", 0) == 0


# ---------------------------------------------------------------------------
# 4. check_clarification: returns token deltas when LLM used, 0/0 otherwise
# ---------------------------------------------------------------------------


def _clarify_openai(payload: dict, in_tok: int = 25, out_tok: int = 8) -> AsyncMock:
    import json

    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    usage = MagicMock()
    usage.prompt_tokens = in_tok
    usage.completion_tokens = out_tok
    completion.usage = usage
    client.chat.completions.create.return_value = completion
    return client


@pytest.mark.asyncio
async def test_check_clarification_llm_path_returns_token_deltas() -> None:
    http = _clarify_openai({"needs_clarification": False, "question": None}, in_tok=25, out_tok=8)
    result = await check_clarification(
        _base_state(),
        langfuse=_langfuse(),
        ai_model_resolver=_resolver_for(http),
    )
    assert result["total_input_tokens"] == 25
    assert result["total_output_tokens"] == 8


@pytest.mark.asyncio
async def test_check_clarification_heuristic_path_returns_zero_deltas() -> None:
    """Heuristic path (no resolver) must return 0/0 — no LLM call made."""
    result = await check_clarification(
        _base_state(),
        langfuse=_langfuse(),
        ai_model_resolver=None,
    )
    assert result.get("total_input_tokens", 0) == 0
    assert result.get("total_output_tokens", 0) == 0


@pytest.mark.asyncio
async def test_check_clarification_llm_error_returns_zero_deltas() -> None:
    """LLM error → heuristic fallback → 0/0 deltas (no partial usage leaked)."""
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    result = await check_clarification(
        _base_state(),
        langfuse=_langfuse(),
        ai_model_resolver=_resolver_for(failing),
    )
    assert result.get("total_input_tokens", 0) == 0
    assert result.get("total_output_tokens", 0) == 0


# ---------------------------------------------------------------------------
# 5. Multi-node accumulation: ≥3 nodes sum correctly via operator.add
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_node_accumulation() -> None:
    """Simulate a 3-node turn; manually apply additive reducer; assert totals."""
    # Node 1: check_clarification (LLM path)
    http1 = _clarify_openai(
        {"needs_clarification": False, "question": None}, in_tok=20, out_tok=6
    )
    clarify_result = await check_clarification(
        _base_state(),
        langfuse=_langfuse(),
        ai_model_resolver=_resolver_for(http1),
    )

    # Node 2: route_sources
    s = _source()
    http2 = _openai_with_usage(
        {"selected_source_ids": [str(s.id)], "use_text_to_query_for": []},
        in_tok=35,
        out_tok=12,
    )
    repo = AsyncMock()
    repo.list_by_ids.return_value = [s]
    router_result = await route_sources(
        _base_state(source_ids=[str(s.id)]),
        ai_model_resolver=_resolver_for(http2),
        db_session=AsyncMock(),
        source_repository=repo,
        langfuse=_langfuse(),
    )

    # Node 3: generate (synthesizer)
    model = _UsageStreamModel("the answer", in_tok=90, out_tok=45)
    gen_result = await generate_response(
        _base_state(),
        ai_model_resolver=_resolver_for(),
        langfuse=_langfuse(),
        chat_model_factory=lambda _c: model,
    )

    # Apply LangGraph's additive reducer manually
    total_in = operator.add(
        operator.add(
            clarify_result["total_input_tokens"],
            router_result["total_input_tokens"],
        ),
        gen_result["total_input_tokens"],
    )
    total_out = operator.add(
        operator.add(
            clarify_result["total_output_tokens"],
            router_result["total_output_tokens"],
        ),
        gen_result["total_output_tokens"],
    )

    assert total_in == 20 + 35 + 90  # 145
    assert total_out == 6 + 12 + 45  # 63
