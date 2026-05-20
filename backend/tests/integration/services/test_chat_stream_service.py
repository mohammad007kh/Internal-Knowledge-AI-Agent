"""Integration tests for :mod:`src.services.chat_stream_service`.

These tests exercise the end-to-end SSE grammar emitted when the
synthesizer node is a real LangChain ``BaseChatModel`` runnable.  The
unit tests in ``tests/unit/services/test_chat_stream_service.py`` mock
``pipeline.astream_events`` directly with hand-rolled event dicts; this
file builds a *real* fake chat model and calls ``astream_events`` on it
to assert the on-wire shape matches what production produces.

The key contract this file pins:

1. **No synthetic tail-delta** when real ``on_chat_model_stream`` events
   fire — the band-aid that used to live in ``run_pipeline_stream`` is
   gone, and the frontend's ``currentResponse`` accumulator is built
   exclusively from native deltas.
2. **No double-rendering** — ``streamed_answer`` and ``final_answer``
   converge for the synthesizer happy path, so the divergence guard in
   the streamer stays silent.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

# Same env-var preamble as other backend tests — required before
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

from src.services.chat_stream_service import (  # noqa: E402
    SANDBOX_SESSION_ID,
    run_pipeline_stream,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in frames:
        m = re.match(r"^event: (\S+)\ndata: (.+)\n\n$", raw, flags=re.DOTALL)
        assert m, f"Frame does not match SSE shape: {raw!r}"
        out.append((m.group(1), json.loads(m.group(2))))
    return out


def _make_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = "trace-1"
    return t


def _pipeline_driving(model: FakeListChatModel, final_answer: str) -> Any:
    """Build a fake pipeline whose ``astream_events`` first re-emits the
    chat model's events, then a synthetic LangGraph ``on_chain_end``
    carrying the canonical final answer.

    This mirrors what the real LangGraph pipeline produces: per-token
    ``on_chat_model_stream`` events bubble up from the synthesizer node,
    followed by a top-level ``on_chain_end`` from the compiled graph.
    """

    pipeline = MagicMock()

    async def _astream(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
        async for ev in model.astream_events(
            [HumanMessage(content="hi")], version="v2"
        ):
            yield ev
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": final_answer, "sources": []}},
        }

    pipeline.astream_events = _astream
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoSyntheticTailDeltaWithRealModel:
    """When the synthesizer streams real tokens, no synthetic delta fires."""

    @pytest.mark.asyncio
    async def test_native_stream_emits_only_real_deltas(self) -> None:
        answer = "Refunds are available within 30 days."
        model = FakeListChatModel(responses=[answer])
        pipeline = _pipeline_driving(model, answer)

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

        # The contract: deltas come from real model events, terminal frame
        # is ``done``, and the concatenated deltas equal the canonical
        # ``final_answer`` exactly — no synthetic tail.
        assert events[-1] == "done"
        delta_tokens = [d["token"] for name, d in parsed if name == "delta"]
        assert "".join(delta_tokens) == answer
        # ``FakeListChatModel`` streams character-by-character; we must
        # see more than one delta to prove the chat-model-stream path
        # actually fired (and we didn't accidentally fall back to a
        # single-shot synthetic).
        assert len(delta_tokens) > 1, (
            "Expected per-character deltas from the real chat model; "
            f"got {len(delta_tokens)} delta(s) — the synthetic-fallback "
            "regression has come back."
        )

    @pytest.mark.asyncio
    async def test_done_event_after_native_stream(self) -> None:
        """A single ``done`` frame closes the SSE stream after real deltas."""
        answer = "ok"
        pipeline = _pipeline_driving(FakeListChatModel(responses=[answer]), answer)

        frames = [
            f
            async for f in run_pipeline_stream(
                pipeline=pipeline,
                initial_state={"session_id": "sess-1"},
                config={"configurable": {"thread_id": "sess-1"}},
                trace_id="trace-9",
                session_id="sess-1",
                langfuse_tracing=_make_tracing(),
                persist_assistant=False,
                on_done=None,
            )
        ]
        parsed = _parse_sse_frames(frames)
        done = [d for name, d in parsed if name == "done"]
        assert len(done) == 1
        assert done[0]["session_id"] == "sess-1"
        assert done[0]["trace_id"] == "trace-9"
