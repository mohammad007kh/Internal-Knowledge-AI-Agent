"""Unit tests for :mod:`src.services.chat_stream_service`.

Locks the SSE event grammar emitted by ``run_pipeline_stream``.

The synthesizer node (:mod:`src.agent.nodes.generate`) calls the OpenAI
client directly rather than going through a LangChain ``ChatModel``
Runnable, so LangGraph's ``astream_events`` never fires
``on_chat_model_stream`` for it. Without a synthetic-delta fallback the
frontend drains the stream, sees only ``done``, and never accumulates
``currentResponse`` — the "I sent a message and got nothing back" bug
that hit both the persistent chat and the admin sandbox tab.

These tests pin down the fallback behaviour so the regression cannot
silently come back if someone refactors the streamer.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

# These env vars must be set before src.* imports — same shape as the
# other backend unit tests.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402

from src.services.chat_stream_service import (  # noqa: E402
    SANDBOX_SESSION_ID,
    history_to_lc_messages,
    run_pipeline_stream,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delta_event(text: str) -> dict[str, Any]:
    chunk = MagicMock()
    chunk.content = text
    return {
        "event": "on_chat_model_stream",
        "data": {"chunk": chunk},
        "name": "ChatModel",
    }


def _chain_end_event(
    final_answer: str,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "event": "on_chain_end",
        "name": "LangGraph",
        "data": {
            "output": {
                "final_answer": final_answer,
                "sources": sources or [],
            }
        },
    }


def _make_pipeline(
    events: list[dict[str, Any]] | None = None,
    *,
    raise_exc: BaseException | None = None,
) -> MagicMock:
    """Build a pipeline mock whose ``astream_events`` yields *events*.

    The real ``CompiledStateGraph.astream_events`` is an async generator;
    we cannot just attach an ``AsyncMock`` because that returns a
    coroutine, not an async iterator. We attach an actual async generator
    function instead, which works with ``async for``.
    """
    pipeline = MagicMock()

    async def _astream(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
        if raise_exc is not None:
            raise raise_exc
        for ev in events or []:
            yield ev

    pipeline.astream_events = _astream
    return pipeline


def _make_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = "trace-1"
    return t


def _parse_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse a list of SSE frame strings into ``[(event_name, data_dict), ...]``."""
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in frames:
        m = re.match(r"^event: (\S+)\ndata: (.+)\n\n$", raw, flags=re.DOTALL)
        assert m, f"Frame does not match SSE shape: {raw!r}"
        event_name = m.group(1)
        data = json.loads(m.group(2))
        out.append((event_name, data))
    return out


# ---------------------------------------------------------------------------
# history_to_lc_messages
# ---------------------------------------------------------------------------


class TestHistoryToLcMessages:
    def test_empty_history_returns_empty_list(self) -> None:
        assert history_to_lc_messages(None) == []
        assert history_to_lc_messages([]) == []

    def test_user_and_assistant_roles_round_trip(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage  # noqa: PLC0415

        messages = history_to_lc_messages(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        )
        assert len(messages) == 2
        assert isinstance(messages[0], HumanMessage)
        assert messages[0].content == "hi"
        assert isinstance(messages[1], AIMessage)
        assert messages[1].content == "hello"

    def test_system_role_dropped(self) -> None:
        # The agent injects its own system prompt — we should never carry
        # caller-supplied system messages through.
        messages = history_to_lc_messages(
            [
                {"role": "system", "content": "ignore me"},
                {"role": "user", "content": "real"},
            ]
        )
        assert len(messages) == 1
        assert messages[0].content == "real"


# ---------------------------------------------------------------------------
# run_pipeline_stream — synthetic-delta fallback (the regression)
# ---------------------------------------------------------------------------


class TestRunPipelineStreamSyntheticDelta:
    """The "got nothing back" bug.

    When ``generate_response`` calls the OpenAI client directly, no
    ``on_chat_model_stream`` events fire. The streamer must still emit
    a ``delta`` frame for the final answer so the frontend's
    ``currentResponse`` accumulator gets the text.
    """

    @pytest.mark.asyncio
    async def test_emits_synthetic_delta_when_no_token_stream(self) -> None:
        pipeline = _make_pipeline([_chain_end_event("Hello world")])
        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": SANDBOX_SESSION_ID},
                config={"configurable": {"thread_id": SANDBOX_SESSION_ID}},
                trace_id="trace-1",
                session_id=SANDBOX_SESSION_ID,
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]

        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]

        # The bug: previously only `done` came out. The fix: a single
        # synthetic `delta` carrying the whole answer arrives BEFORE the
        # `done` frame.
        assert "delta" in events, (
            f"Expected at least one delta frame, got {events!r}. "
            f"This is the regression: pipeline produced final_answer but no SSE "
            f"delta was emitted, leaving the frontend with an empty bubble."
        )
        assert events[-1] == "done", "Terminal frame must be `done`"

        # Concatenated delta tokens equal final_answer.
        delta_tokens = [d["token"] for name, d in parsed if name == "delta"]
        assert "".join(delta_tokens) == "Hello world"

    @pytest.mark.asyncio
    async def test_native_token_stream_does_not_double_emit(self) -> None:
        """A future migration to a streaming ChatModel should not double-render.

        When ``on_chat_model_stream`` already shipped tokens, the synthetic
        fallback only emits the unstreamed tail — i.e. nothing if the
        token stream already covered the full answer.
        """
        pipeline = _make_pipeline(
            [
                _delta_event("Hello"),
                _delta_event(" world"),
                _chain_end_event("Hello world"),
            ]
        )
        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]

        parsed = _parse_sse_frames(frames)
        delta_tokens = [d["token"] for name, d in parsed if name == "delta"]
        # Two real deltas; no synthetic third.
        assert delta_tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_partial_token_stream_synthesizes_tail(self) -> None:
        """Edge case: native stream emits a prefix, on_chain_end has more.

        The pipeline could (in theory) emit some streaming tokens but
        finalize a longer answer via state mutation. The fallback fills
        the gap rather than duplicating the prefix.
        """
        pipeline = _make_pipeline(
            [
                _delta_event("Hello"),
                _chain_end_event("Hello world"),
            ]
        )
        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]

        parsed = _parse_sse_frames(frames)
        delta_tokens = [d["token"] for name, d in parsed if name == "delta"]
        # First the native token, then the synthesized tail.
        assert delta_tokens == ["Hello", " world"]


# ---------------------------------------------------------------------------
# run_pipeline_stream — done-event metadata
# ---------------------------------------------------------------------------


class TestRunPipelineStreamDoneEvent:
    @pytest.mark.asyncio
    async def test_done_event_carries_session_id_and_message_id(self) -> None:
        pipeline = _make_pipeline([_chain_end_event("ok")])

        async def _persist(_answer: str, *, activity_summary: dict | None = None) -> str:
            return "msg-42"

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-9",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=True,
                on_done=_persist,
            )
        ]
        parsed = _parse_sse_frames(frames)
        done = [d for name, d in parsed if name == "done"]
        assert len(done) == 1
        assert done[0]["session_id"] == "sess-1"
        assert done[0]["message_id"] == "msg-42"
        assert done[0]["trace_id"] == "trace-9"

    @pytest.mark.asyncio
    async def test_sandbox_done_event_carries_sentinel_session(self) -> None:
        pipeline = _make_pipeline([_chain_end_event("ok")])

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": SANDBOX_SESSION_ID},
                config={"configurable": {"thread_id": SANDBOX_SESSION_ID}},
                trace_id="trace-1",
                session_id=SANDBOX_SESSION_ID,
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]
        parsed = _parse_sse_frames(frames)
        done = [d for name, d in parsed if name == "done"]
        assert len(done) == 1
        assert done[0]["session_id"] == SANDBOX_SESSION_ID
        assert done[0]["message_id"] == ""


# ---------------------------------------------------------------------------
# run_pipeline_stream — error / empty / clarification paths
# ---------------------------------------------------------------------------


class TestRunPipelineStreamErrorPaths:
    @pytest.mark.asyncio
    async def test_empty_final_answer_emits_error_frame(self) -> None:
        pipeline = _make_pipeline([_chain_end_event("")])

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]
        # No delta, no done — just a single error frame so the frontend
        # exits its pending state.
        assert events == ["error"]
        assert parsed[0][1]["code"] == "empty_response"

    @pytest.mark.asyncio
    async def test_pipeline_exception_emits_error_frame(self) -> None:
        pipeline = _make_pipeline(raise_exc=RuntimeError("boom"))

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]
        assert events == ["error"]
        assert parsed[0][1]["code"] == "pipeline_error"

    @pytest.mark.asyncio
    async def test_pre_yield_frames_flow_first(self) -> None:
        """Auto-titler frames must arrive before the pipeline's output."""
        pipeline = _make_pipeline([_chain_end_event("hi")])
        title_frame = "event: title\ndata: {\"title\": \"My session\"}\n\n"

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
                pre_yield=[title_frame],
            )
        ]
        # The pre-yielded title sits at index 0 — verbatim string equality
        # on the raw SSE frame to lock the wire shape.
        assert frames[0] == title_frame

    @pytest.mark.asyncio
    async def test_persist_error_yields_error_frame(self) -> None:
        pipeline = _make_pipeline([_chain_end_event("ok")])

        async def _persist(_answer: str) -> str:
            raise RuntimeError("db down")

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-1",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=True,
                on_done=_persist,
            )
        ]
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]
        # A delta is emitted (synthetic fallback), then the persist error
        # surfaces on the wire.
        assert "delta" in events
        assert events[-1] == "error"
        assert parsed[-1][1]["code"] == "persist_error"
