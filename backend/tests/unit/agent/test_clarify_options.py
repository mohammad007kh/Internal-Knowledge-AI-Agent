"""T-080 — extended ``clarification`` SSE event with structured options.

Locks the additive contract for the ``clarification`` event (spec
``contracts/sse-events.md`` §"Extended event: clarification"):

```jsonc
event: clarification
data: {
  "question": "Which users did you mean?",
  "options": [
    {"id": "hr", "label": "Employees", "hint": "HR database", "recommended": false},
    {"id": "crm", "label": "Customers", "hint": "CRM file", "recommended": true}
  ],
  "allow_free_text": true
}
```

The agentic graph ends the clarification turn NORMALLY (``planner →
handle_clarification → END``) — no ``interrupt()``, no ``GraphInterrupt``.
``clarification_question`` / ``clarification_options`` ride out on the final
LangGraph state.  ``run_pipeline_stream`` detects them and emits the extended
event TERMINALLY (the turn ends; no ``step`` / ``delta`` / ``done`` answer
frames follow).  The legacy ``GraphInterrupt``-string path stays valid
(additive).

Five coverage areas (T-080 build spec):

* (a) extended event serializes options matching the wire contract;
* (b) ``2 ≤ len(options) ≤ 4`` enforced (1 or 5 → Pydantic ``ValidationError``);
* (c) legacy NO-options emission still valid (additive);
* (d) options clipped to the user's permitted source set (an inaccessible
      source is never produced);
* (e) the clarification path is TERMINAL — no ``step`` events follow, no
      interrupt / checkpointer.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

# These env vars must be set before src.* imports — same shape as the other
# backend unit tests.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.schemas.chat import ChatStreamEvent, StreamEventType  # noqa: E402
from src.services.chat_stream_service import (  # noqa: E402
    SANDBOX_SESSION_ID,
    run_pipeline_stream,
)

# ---------------------------------------------------------------------------
# Helpers (mirror tests/unit/services/test_chat_stream_service.py)
# ---------------------------------------------------------------------------


def _clarification_chain_end(
    *,
    question: str,
    options: list[dict[str, Any]] | None,
    final_answer: str | None = None,
) -> dict[str, Any]:
    """A terminal ``LangGraph`` ``on_chain_end`` carrying clarification state.

    Mirrors the agentic graph's clarification terminal: planner sets
    ``requires_clarification`` + ``clarification_question`` +
    ``clarification_options``; ``handle_clarification`` echoes the question into
    ``final_answer`` and routes to END.  No exception is raised.
    """
    output: dict[str, Any] = {
        "requires_clarification": True,
        "clarification_question": question,
        "final_answer": final_answer if final_answer is not None else question,
        "sources": [],
    }
    if options is not None:
        output["clarification_options"] = options
    return {
        "event": "on_chain_end",
        "name": "LangGraph",
        "data": {"output": output},
    }


def _chain_end_event(final_answer: str) -> dict[str, Any]:
    return {
        "event": "on_chain_end",
        "name": "LangGraph",
        "data": {"output": {"final_answer": final_answer, "sources": []}},
    }


def _node_end_event(name: str, output: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    return {
        "event": "on_chain_end",
        "name": name,
        "run_id": run_id,
        "data": {"output": output},
    }


def _make_pipeline(events: list[dict[str, Any]]) -> MagicMock:
    pipeline = MagicMock()

    async def _astream(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
        for ev in events:
            yield ev

    pipeline.astream_events = _astream
    return pipeline


def _make_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = "trace-1"
    return t


def _parse_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in frames:
        m = re.match(r"^event: (\S+)\ndata: (.+)\n\n$", raw, flags=re.DOTALL)
        assert m, f"Frame does not match SSE shape: {raw!r}"
        out.append((m.group(1), json.loads(m.group(2))))
    return out


# Permitted source set the requesting user can see (the re-clip authority).
PERMITTED_IDS = ["src-001", "src-002", "src-003"]


async def _collect(
    pipeline: MagicMock,
    *,
    session_id: str = "sess-1",
    source_ids: list[str] | None = None,
) -> list[str]:
    initial_state: dict[str, Any] = {"session_id": session_id}
    if source_ids is not None:
        initial_state["source_ids"] = source_ids
    return [
        f
        async for f in run_pipeline_stream(
            pipeline=pipeline,
            initial_state=initial_state,
            config={"configurable": {"thread_id": session_id}},
            trace_id="trace-1",
            session_id=session_id,
            langfuse_tracing=_make_tracing(),
            persist_assistant=False,
            on_done=None,
        )
    ]


# ---------------------------------------------------------------------------
# (b) Schema: ClarificationData / ClarificationOption — Pydantic v2 contract
# ---------------------------------------------------------------------------


class TestClarificationSchema:
    def test_clarification_option_minimal_fields(self) -> None:
        opt = ChatStreamEvent.ClarificationOption(id="hr", label="Employees")
        assert opt.id == "hr"
        assert opt.label == "Employees"
        assert opt.hint is None
        assert opt.recommended is None

    def test_clarification_option_full_fields(self) -> None:
        opt = ChatStreamEvent.ClarificationOption(
            id="crm", label="Customers", hint="CRM file", recommended=True
        )
        assert opt.hint == "CRM file"
        assert opt.recommended is True

    def test_legacy_no_options_is_valid(self) -> None:
        """(c) Question-only clarification (options absent) stays valid."""
        data = ChatStreamEvent.ClarificationData(question="Clarify?")
        assert data.options is None
        assert data.allow_free_text is True

    def test_two_options_valid(self) -> None:
        data = ChatStreamEvent.ClarificationData(
            question="Which?",
            options=[
                ChatStreamEvent.ClarificationOption(id="a", label="A"),
                ChatStreamEvent.ClarificationOption(id="b", label="B"),
            ],
        )
        assert len(data.options or []) == 2

    def test_four_options_valid(self) -> None:
        data = ChatStreamEvent.ClarificationData(
            question="Which?",
            options=[
                ChatStreamEvent.ClarificationOption(id=str(i), label=f"O{i}")
                for i in range(4)
            ],
        )
        assert len(data.options or []) == 4

    def test_one_option_rejected(self) -> None:
        """(b) A single option violates the 2-4 contract → ValidationError."""
        with pytest.raises(ValidationError):
            ChatStreamEvent.ClarificationData(
                question="Which?",
                options=[ChatStreamEvent.ClarificationOption(id="a", label="A")],
            )

    def test_five_options_rejected(self) -> None:
        """(b) Five options violate the 2-4 contract → ValidationError."""
        with pytest.raises(ValidationError):
            ChatStreamEvent.ClarificationData(
                question="Which?",
                options=[
                    ChatStreamEvent.ClarificationOption(id=str(i), label=f"O{i}")
                    for i in range(5)
                ],
            )

    def test_allow_free_text_defaults_true(self) -> None:
        data = ChatStreamEvent.ClarificationData(question="Q")
        assert data.allow_free_text is True

    def test_allow_free_text_can_be_disabled(self) -> None:
        data = ChatStreamEvent.ClarificationData(question="Q", allow_free_text=False)
        assert data.allow_free_text is False


# ---------------------------------------------------------------------------
# (a) Factory: ChatStreamEvent.clarification(...) — wire shape
# ---------------------------------------------------------------------------


class TestClarificationFactory:
    def test_legacy_question_only_factory(self) -> None:
        """(c) Legacy free-text factory: question only, no options key needed."""
        evt = ChatStreamEvent.clarification("Could you clarify?")
        assert evt.event == StreamEventType.CLARIFICATION
        assert evt.data["question"] == "Could you clarify?"
        # additive: allow_free_text always present (defaults true), options None.
        assert evt.data["allow_free_text"] is True
        assert evt.data.get("options") is None

    def test_factory_with_options_wire_shape(self) -> None:
        """(a) Options serialize to the contract shape {id,label,hint?,recommended?}."""
        evt = ChatStreamEvent.clarification(
            "Which users did you mean?",
            options=[
                {"id": "hr", "label": "Employees", "hint": "HR database", "recommended": False},
                {"id": "crm", "label": "Customers", "hint": "CRM file", "recommended": True},
            ],
        )
        data = evt.data
        assert data["question"] == "Which users did you mean?"
        assert data["allow_free_text"] is True
        assert isinstance(data["options"], list)
        assert len(data["options"]) == 2
        first = data["options"][0]
        assert first == {
            "id": "hr",
            "label": "Employees",
            "hint": "HR database",
            "recommended": False,
        }
        # to_sse round-trips as valid JSON under the clarification event name.
        m = re.match(r"^event: clarification\ndata: (.+)\n\n$", evt.to_sse(), flags=re.DOTALL)
        assert m
        reparsed = json.loads(m.group(1))
        assert reparsed["options"][1]["recommended"] is True

    def test_factory_one_option_raises(self) -> None:
        """(b) 1 option → ValidationError surfaced from the factory."""
        with pytest.raises(ValidationError):
            ChatStreamEvent.clarification(
                "Which?", options=[{"id": "a", "label": "A"}]
            )

    def test_factory_five_options_raises(self) -> None:
        """(b) 5 options → ValidationError surfaced from the factory."""
        with pytest.raises(ValidationError):
            ChatStreamEvent.clarification(
                "Which?",
                options=[{"id": str(i), "label": f"O{i}"} for i in range(5)],
            )

    def test_factory_allow_free_text_passthrough(self) -> None:
        evt = ChatStreamEvent.clarification(
            "Which?",
            options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            allow_free_text=False,
        )
        assert evt.data["allow_free_text"] is False


# ---------------------------------------------------------------------------
# run_pipeline_stream — terminal clarification emission (decision b)
# ---------------------------------------------------------------------------


class TestClarificationStreamTerminal:
    @pytest.mark.asyncio
    async def test_agentic_clarification_emits_extended_event(self) -> None:
        """(a) Final agentic state with options → extended clarification frame."""
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which source did you mean?",
                    options=[
                        {"source_id": "src-001", "source_name": "Sales DB"},
                        {"source_id": "src-002", "source_name": "HR Policies"},
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]

        assert events == ["clarification"], (
            f"Clarification must be the SINGLE terminal frame, got {events!r}"
        )
        data = parsed[0][1]
        assert data["question"] == "Which source did you mean?"
        assert data["allow_free_text"] is True
        assert len(data["options"]) == 2
        # Planner shape {source_id, source_name} → wire {id, label}, where the
        # wire label is the TRUSTED server-loaded source_name (FX41 clause 2).
        opt_ids = {o["id"] for o in data["options"]}
        assert opt_ids == {"src-001", "src-002"}
        labels = {o["label"] for o in data["options"]}
        assert labels == {"Sales DB", "HR Policies"}

    @pytest.mark.asyncio
    async def test_clarification_is_terminal_no_step_no_done(self) -> None:
        """(e) Clarification is TERMINAL: no step / delta / done answer frames follow."""
        pipeline = _make_pipeline(
            [
                # An intermediate plan-ish node could fire in theory; the
                # clarification terminal must still suppress the answer frames.
                _node_end_event(
                    "planner",
                    {
                        "requires_clarification": True,
                        "clarification_question": "Which?",
                        "clarification_options": [
                            {"source_id": "src-001", "source_name": "Sales DB"},
                            {"source_id": "src-002", "source_name": "HR Policies"},
                        ],
                    },
                    run_id="run-1",
                ),
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        {"source_id": "src-001", "source_name": "Sales DB"},
                        {"source_id": "src-002", "source_name": "HR Policies"},
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        events = [name for name, _ in _parse_sse_frames(frames)]
        assert "step" not in events
        assert "delta" not in events
        assert "done" not in events
        assert events[-1] == "clarification"

    @pytest.mark.asyncio
    async def test_options_clipped_to_permitted_set(self) -> None:
        """(d) An option naming an inaccessible source is excluded server-side."""
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        {"source_id": "src-001", "source_name": "Sales DB"},
                        {"source_id": "src-EVIL", "source_name": "Evil leaked source"},
                        {"source_id": "src-002", "source_name": "HR Policies"},
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        data = parsed[0][1]
        opt_ids = {o["id"] for o in data["options"]}
        assert "src-EVIL" not in opt_ids
        assert opt_ids == {"src-001", "src-002"}
        # The inaccessible source's NAME must never appear on the wire.
        assert "Evil leaked source" not in json.dumps(data)

    @pytest.mark.asyncio
    async def test_clipping_below_two_falls_back_to_free_text(self) -> None:
        """(d)+(b) If clipping leaves <2 options, degrade to legacy free-text.

        Surfacing a single option would violate the 2-4 contract; the right
        move is a question-only clarification (still terminal, still valid).
        """
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        {"source_id": "src-001", "source_name": "Sales DB"},
                        {"source_id": "src-EVIL", "source_name": "Evil"},
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]
        assert events == ["clarification"]
        data = parsed[0][1]
        # Only one option survived the clip → cannot meet 2-4 → free-text.
        assert data.get("options") is None
        assert data["allow_free_text"] is True
        assert data["question"] == "Which?"

    @pytest.mark.asyncio
    async def test_clipping_caps_at_four(self) -> None:
        """(b) More than 4 permitted options are capped to 4 on the wire."""
        permitted = [f"src-{i:03d}" for i in range(6)]
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        {"source_id": f"src-{i:03d}", "source_name": f"Source {i}"}
                        for i in range(6)
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=permitted)
        parsed = _parse_sse_frames(frames)
        data = parsed[0][1]
        assert 2 <= len(data["options"]) <= 4

    @pytest.mark.asyncio
    async def test_no_options_state_emits_legacy_free_text(self) -> None:
        """(c) Agentic clarification with NO options → legacy question-only frame."""
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(question="Please clarify.", options=None),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        events = [name for name, _ in parsed]
        assert events == ["clarification"]
        data = parsed[0][1]
        assert data["question"] == "Please clarify."
        assert data.get("options") is None
        assert data["allow_free_text"] is True

    @pytest.mark.asyncio
    async def test_option_label_html_escaped(self) -> None:
        """Trusted source names are HTML-escaped (planner discipline parity).

        The wire label is the TRUSTED ``source_name`` (not LLM free text); if a
        source's actual display name contains HTML metacharacters they are still
        escaped, mirroring the planner's ``_render_sources_block``.
        """
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        {"source_id": "src-001", "source_name": "<script>alert(1)</script>"},
                        {"source_id": "src-002", "source_name": "HR & Legal"},
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        labels = {o["label"] for o in parsed[0][1]["options"]}
        assert "<script>alert(1)</script>" not in labels
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in labels
        assert "HR &amp; Legal" in labels

    @pytest.mark.asyncio
    async def test_permitted_option_label_naming_inaccessible_source_is_scrubbed(
        self,
    ) -> None:
        """FX41 clause 2: a PERMITTED source_id whose planner label/hint NAMES an
        inaccessible source must NOT leak that name on the wire.

        Even though ``src-001`` IS permitted, an attacker-influenced planner
        could attach a free-text ``label``/``hint`` that names a source the user
        cannot see (e.g. ``SECRET-PAYROLL-DB``).  The emitter must re-key the
        wire label to the TRUSTED ``source_name`` of the SAME permitted source
        (clause-2 boundary re-clip), so the leaked string never appears anywhere
        in the serialized frame.
        """
        leaked = "See SECRET-PAYROLL-DB"
        leaked_hint = "joins to PAYROLL-PII source"
        pipeline = _make_pipeline(
            [
                _clarification_chain_end(
                    question="Which?",
                    options=[
                        # Permitted id, but the LLM-authored label + hint NAME an
                        # inaccessible source.  The planner attaches the trusted
                        # name; the emitter must prefer it and drop the free text.
                        {
                            "source_id": "src-001",
                            "source_name": "Sales DB",
                            "label": leaked,
                            "hint": leaked_hint,
                        },
                        {
                            "source_id": "src-002",
                            "source_name": "HR Policies",
                            "label": "Another leak: CONFIDENTIAL-VAULT",
                            "hint": "do not show",
                        },
                    ],
                ),
            ]
        )
        frames = await _collect(pipeline, source_ids=PERMITTED_IDS)
        parsed = _parse_sse_frames(frames)
        data = parsed[0][1]

        # Both permitted ids survive; labels are the TRUSTED names, not LLM text.
        opt_ids = {o["id"] for o in data["options"]}
        assert opt_ids == {"src-001", "src-002"}
        labels = {o["label"] for o in data["options"]}
        assert labels == {"Sales DB", "HR Policies"}

        # No option carries a hint (dropped — no trusted per-source hint).
        assert all("hint" not in o for o in data["options"])

        # The leaked names must NOT appear anywhere in the serialized frame.
        serialized = json.dumps(data)
        assert leaked not in serialized
        assert "SECRET-PAYROLL-DB" not in serialized
        assert leaked_hint not in serialized
        assert "CONFIDENTIAL-VAULT" not in serialized
        assert "PAYROLL-PII" not in serialized

    @pytest.mark.asyncio
    async def test_normal_answer_still_emits_delta_and_done(self) -> None:
        """A non-clarification turn is byte-identical to before (no regression)."""
        pipeline = _make_pipeline([_chain_end_event("Hello world")])
        frames = await _collect(pipeline)
        events = [name for name, _ in _parse_sse_frames(frames)]
        assert "clarification" not in events
        assert "delta" in events
        assert events[-1] == "done"


# ---------------------------------------------------------------------------
# Legacy GraphInterrupt-string path stays valid (additive)
# ---------------------------------------------------------------------------


class TestLegacyGraphInterruptPath:
    @pytest.mark.asyncio
    async def test_graph_interrupt_string_still_emits_clarification(self) -> None:
        """(c) The historical GraphInterrupt(str) bridge still works (no options)."""
        try:
            from langgraph.errors import GraphInterrupt  # noqa: PLC0415
        except ImportError:  # pragma: no cover - langgraph always present here
            pytest.skip("langgraph not installed")

        pipeline = MagicMock()

        async def _astream(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
            raise GraphInterrupt("Need more detail?")
            yield  # pragma: no cover - unreachable, makes this an async generator

        pipeline.astream_events = _astream

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
        assert events == ["clarification"]
        data = parsed[0][1]
        # Legacy path: question only, options absent, free-text on.
        assert data.get("options") is None
        assert data["allow_free_text"] is True
        assert isinstance(data["question"], str) and data["question"]
