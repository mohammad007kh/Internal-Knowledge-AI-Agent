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


_node_run_seq = 0


def _node_end_event(
    name: str,
    output: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """An intermediate agentic node ``on_chain_end`` event.

    Mirrors ``astream_events(version="v2")``: ``event["name"]`` is the node
    name, ``event["data"]["output"]`` is the node's returned state-delta, and
    ``event["run_id"]`` is unique per node completion (the dedup key).
    """
    global _node_run_seq  # noqa: PLW0603
    if run_id is None:
        _node_run_seq += 1
        run_id = f"run-{_node_run_seq}"
    return {
        "event": "on_chain_end",
        "name": name,
        "run_id": run_id,
        "data": {"output": output},
    }


def _plan_delta(*, revision: int = 0, reason: Any = None, n_steps: int = 2) -> dict[str, Any]:
    """A planner node delta carrying ``plan_event_data`` (contract shape)."""
    return {
        "plan": [{"id": f"s{i}"} for i in range(1, n_steps + 1)],
        "plan_event_data": {
            "revision": revision,
            "reason": reason,
            "steps": [
                {
                    "id": f"s{i}",
                    "label": f"step {i}",
                    "source_id": f"src-{i}",
                    "source_name": f"Source {i}",
                    "depends_on": [],
                }
                for i in range(1, n_steps + 1)
            ],
        },
    }


def _step_delta(step_id: str, states: list[str]) -> dict[str, Any]:
    """An executor node delta carrying a LIST of step events (started/finished…)."""
    return {
        "step_event_data": [
            {
                "step_id": step_id,
                "role": "executor",
                "state": st,
                "label": f"{step_id} {st}",
                "summary": None,
                "progress": {"current": 1, "total": 1},
            }
            for st in states
        ],
    }


def _budget_delta(not_completed: list[str] | None = None) -> dict[str, Any]:
    """A budget_guard node delta carrying ``budget_event_data`` (contract shape)."""
    return {
        "budget_hit": True,
        "budget_event_data": {
            "ceiling_hit": True,
            "not_completed": not_completed or ["finish the answer"],
            "offer_continue": True,
        },
    }


def _replan_delta(reason: str = "switching sources") -> dict[str, Any]:
    """A replan node delta carrying BOTH replan + fresh plan event data (T-056)."""
    return {
        "replan_event_data": {"reason": reason, "superseded_revision": 0},
        "plan_event_data": {
            "revision": 1,
            "reason": reason,
            "steps": [
                {
                    "id": "s1",
                    "label": "revised step",
                    "source_id": "src-1",
                    "source_name": "Source 1",
                    "depends_on": [],
                }
            ],
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


# ---------------------------------------------------------------------------
# run_pipeline_stream — agentic intermediate-frame emitter (PART 1)
# ---------------------------------------------------------------------------


async def _collect(pipeline: MagicMock, *, session_id: str = "sess-1") -> list[str]:
    return [
        f
        async for f in run_pipeline_stream(
            pipeline=pipeline,
            initial_state={"session_id": session_id},
            config={"configurable": {"thread_id": session_id}},
            trace_id="trace-1",
            session_id=session_id,
            langfuse_tracing=_make_tracing(),
            persist_assistant=False,
            on_done=None,
        )
    ]


class TestRunPipelineStreamAgenticEmitter:
    """The agentic SSE emitter: per-node ``*_event_data`` → wire frames.

    Locks frame ordering, one-frame-per-event, the replan-then-plan order
    (T-056), and that the v2 path (no ``*_event_data``) is byte-identical to
    before (only ``delta`` + ``done``).
    """

    @pytest.mark.asyncio
    async def test_plan_steps_budget_then_done_in_order(self) -> None:
        # Synthetic node completions in execution order: planner → executor
        # (started + finished) → budget → terminal LangGraph end.
        pipeline = _make_pipeline(
            [
                _node_end_event("planner", _plan_delta(n_steps=2)),
                _node_end_event("execute_step", _step_delta("s1", ["started", "finished"])),
                _node_end_event("budget_guard_step", _budget_delta()),
                _chain_end_event("Final answer"),
            ]
        )
        frames = await _collect(pipeline)
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]

        # plan, two steps, budget, then a delta (synthetic fallback) and done.
        assert events[0] == "plan"
        assert events[1] == "step"
        assert events[2] == "step"
        assert events[3] == "budget"
        assert events[-1] == "done"
        # Exactly one of each intermediate type, two steps.
        assert events.count("plan") == 1
        assert events.count("step") == 2
        assert events.count("budget") == 1

        # Payloads pass through verbatim (contract shape — NOT reshaped).
        plan_payload = parsed[0][1]
        assert plan_payload["revision"] == 0
        assert len(plan_payload["steps"]) == 2
        step_states = [d["state"] for n, d in parsed if n == "step"]
        assert step_states == ["started", "finished"]
        budget_payload = parsed[3][1]
        assert budget_payload == {
            "ceiling_hit": True,
            "not_completed": ["finish the answer"],
            "offer_continue": True,
        }

    @pytest.mark.asyncio
    async def test_each_node_frame_emitted_exactly_once(self) -> None:
        # Same planner node output surfaced TWICE with the SAME run_id — the
        # dedup must collapse it to a single plan frame.
        plan_evt = _node_end_event("planner", _plan_delta(n_steps=1), run_id="dup-1")
        pipeline = _make_pipeline(
            [plan_evt, plan_evt, _chain_end_event("ok")]
        )
        frames = await _collect(pipeline)
        events = [name for name, _ in _parse_sse_frames(frames)]
        assert events.count("plan") == 1

    @pytest.mark.asyncio
    async def test_replan_then_plan_order(self) -> None:
        # The replan node returns BOTH replan + fresh plan in one delta; the
        # emitter must yield replan FIRST, then the fresh plan (T-056).
        pipeline = _make_pipeline(
            [
                _node_end_event("planner", _plan_delta(n_steps=1)),
                _node_end_event("execute_step", _step_delta("s1", ["started", "failed"])),
                _node_end_event("replan", _replan_delta()),
                _node_end_event("execute_step", _step_delta("s1", ["started", "finished"])),
                _chain_end_event("ok"),
            ]
        )
        frames = await _collect(pipeline)
        events = [name for name, _ in _parse_sse_frames(frames)]
        # The replan event sits immediately before the revised plan event.
        replan_idx = events.index("replan")
        assert events[replan_idx + 1] == "plan"
        # Two plans total (initial + revision), one replan.
        assert events.count("replan") == 1
        assert events.count("plan") == 2

    @pytest.mark.asyncio
    async def test_v2_path_unchanged_only_delta_and_done(self) -> None:
        # A v2 turn: token stream + terminal end, NO ``*_event_data`` node deltas.
        # The emitter must be a no-op → byte-identical to the pre-emitter wire.
        pipeline = _make_pipeline(
            [
                _delta_event("Hello"),
                _delta_event(" world"),
                _chain_end_event("Hello world"),
            ]
        )
        frames = await _collect(pipeline)
        events = [name for name, _ in _parse_sse_frames(frames)]
        assert events == ["delta", "delta", "done"]

    @pytest.mark.asyncio
    async def test_malformed_node_delta_does_not_break_stream(self) -> None:
        # A node whose output is not the expected dict shape (e.g. event_data is
        # a string) must be skipped silently — the stream still completes.
        pipeline = _make_pipeline(
            [
                _node_end_event("planner", {"plan_event_data": "not-a-dict"}),
                _node_end_event("execute_step", {"step_event_data": "not-a-list"}),
                _chain_end_event("Final answer"),
            ]
        )
        frames = await _collect(pipeline)
        events = [name for name, _ in _parse_sse_frames(frames)]
        # No plan/step frames from the malformed deltas; stream still ends.
        assert "plan" not in events
        assert "step" not in events
        assert events[-1] == "done"
