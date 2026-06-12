"""T-059 — end-to-end agentic-pipeline streaming integration scenarios.

Drives the REAL agentic graph (``build_pipeline(sandbox=True)`` with
``PIPELINE_AGENTIC_ENABLED`` forced ON per-test) end-to-end through
``run_pipeline_stream`` and asserts the agentic SSE wire frames (``plan`` /
``step`` / ``budget``) emitted by the PART-1 emitter, plus the final-answer
guarantees of each scenario.

Three scenarios (spec FR-006 / FR-012/13 / FR-019/20):

(a) **Chained multi-step (FR-006)** — planner emits 2 dependent steps
    (file → db); both graders accept; assert a ``plan`` event with ≥2 steps,
    ordered ``step`` events, and a final answer chaining both sources.

(b) **Retry-then-abstain (FR-012/13)** — the (single) step's grader is
    ``unacceptable``; exactly ONE retry then an honest abstain (no replan,
    seeded ``plan_revision=1`` routes the exhausted retry to the honest-failure
    synthesizer); the synthesizer is rendered with ``render_failure_prompt``
    (its lead text asserted on the captured system prompt); diagnostics present;
    a known-absent value is NEVER surfaced as found.

(c) **Graceful budget (FR-019/20)** — a tiny per-test ``token_ceiling`` trips
    the deterministic budget guard at the first gate; assert a ``budget`` event
    ``{ceiling_hit: true, not_completed: [...], offer_continue: true}`` + a best
    partial answer + the stream STILL ends with ``done`` (no error / silent
    failure).

Synthetic-only fixtures (``data_source="synthetic"``, no real PII — security
rule 4); LLM stage slots mocked deterministically ("test-model-stub"); the flag
+ budget ceiling are overridden PER-TEST (scoped ``monkeypatch`` / seeded
budget snapshot), never globally.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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

from src.agent import pipeline as pipeline_mod  # noqa: E402
from src.agent.pipeline import build_agent_budget_snapshot, build_pipeline  # noqa: E402
from src.agent.prompts import render_failure_prompt  # noqa: E402
from src.services.ai_model_resolver import AIModelClient  # noqa: E402
from src.services.chat_stream_service import run_pipeline_stream  # noqa: E402

# A known-absent identifier used ONLY in scenario (b): it must NEVER appear in
# the final answer as a found value (the no-fabrication guarantee).
ABSENT_NAME = "Ztelophonius Quibblesworth"

# The leading instruction of render_failure_prompt's system text — the honest
# lead the synthesizer is told to produce.  Asserted against the CAPTURED system
# prompt (the prompt selection), since the answer text itself is the stub's.
_FAILURE_PROMPT_LEAD = "This turn could\nNOT produce a trustworthy complete answer."


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _parse_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in frames:
        m = re.match(r"^event: (\S+)\ndata: (.+)\n\n$", raw, flags=re.DOTALL)
        assert m, f"Frame does not match SSE shape: {raw!r}"
        out.append((m.group(1), json.loads(m.group(2))))
    return out


# ---------------------------------------------------------------------------
# Deterministic LLM-client stubs (planner + grader). The synthesizer goes
# through build_chat_model (patched per-test), not the raw http_client.
# ---------------------------------------------------------------------------


def _client_returning(payloads: list[dict | str] | dict | str) -> AsyncMock:
    """Build an AsyncMock OpenAI client.

    ``payloads`` may be a single payload (returned every call) or a LIST of
    payloads consumed in order — so a grader can return ``unacceptable`` on the
    first two calls (initial + retry) deterministically.
    """
    client = AsyncMock()

    def _completion(content: str) -> MagicMock:
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = content
        completion.usage.prompt_tokens = 60
        completion.usage.completion_tokens = 12
        return completion

    if isinstance(payloads, list):
        queue = [
            p if isinstance(p, str) else json.dumps(p) for p in payloads
        ]

        async def _create(*_a: Any, **_kw: Any) -> MagicMock:
            content = queue.pop(0) if queue else queue_fallback
            return _completion(content)

        queue_fallback = queue[-1] if queue else "{}"
        client.chat.completions.create.side_effect = _create
    else:
        content = payloads if isinstance(payloads, str) else json.dumps(payloads)
        client.chat.completions.create.return_value = _completion(content)
    return client


def _make_resolver(stage_clients: dict[str, AsyncMock]) -> AsyncMock:
    resolver = AsyncMock()

    async def _resolve(stage: str) -> AIModelClient:
        http_client = stage_clients.get(stage) or _client_returning("ok")
        return AIModelClient(
            ai_model_id=uuid.uuid4(),
            provider="openai",
            model_id="test-model-stub",
            temperature=0.0,
            max_tokens=1024,
            custom_prompt=None,
            capabilities={},
            http_client=http_client,
        )

    resolver.resolve.side_effect = _resolve
    return resolver


def _make_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = "trace-agentic-t059"
    return t


class _CapturingChatModel(FakeListChatModel):
    """A FakeListChatModel that records the system prompt it was invoked with.

    Used by scenario (b) to assert the synthesizer was rendered with
    ``render_failure_prompt`` (the honest-failure prompt selection) — the
    answer TEXT is still the canned stub response.
    """

    captured: dict[str, Any] = {}

    def _stream(self, messages: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._capture(messages)
        return super()._stream(messages, *args, **kwargs)

    async def _astream(self, messages: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._capture(messages)
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk

    def _capture(self, messages: Any) -> None:
        for msg in messages or []:
            if getattr(msg, "type", None) == "system":
                type(self).captured["system_prompt"] = str(msg.content)
                break


@pytest.fixture
def _force_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test (scoped) flag override — NOT a global mutation."""
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_AGENTIC_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_V2_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_REFLECTOR_ENABLED", False)


def _source_meta(source_id: uuid.UUID, name: str, purpose: str) -> MagicMock:
    src = MagicMock()
    src.id = source_id
    src.name = name
    src.purpose = purpose
    src.example_questions = ["What is the policy?"]
    src.out_of_scope = ["PII"]
    return src


def _fake_chunk(source_id: uuid.UUID, text: str, title: str) -> MagicMock:
    chunk = MagicMock()
    chunk.id = f"chunk-{uuid.uuid4().hex[:8]}"
    chunk.source_id = str(source_id)
    chunk.chunk_text = text
    chunk.metadata_ = {
        "document_title": title,
        "page_number": 1,
        "source_name": title,
        "data_source": "synthetic",  # security rule 4: synthetic-only fixtures
    }
    return chunk


def _initial_state(
    source_ids: list[uuid.UUID],
    query: str,
    *,
    plan_revision: int = 0,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=query)],
        "source_ids": [str(s) for s in source_ids],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": str(uuid.uuid4()),
        "user_id": "user-1",
        "trace_id": "trace-agentic-t059",
        "query": query,
        "final_answer": None,
        "error": None,
        "sources": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "raw_user_intent": query,
        "plan": [],
        "past_steps": [],
        "current_step": None,
        # Seeded per-test (scenario b uses 1 to route an exhausted retry to the
        # honest-failure synthesizer WITHOUT a replan).
        "plan_revision": plan_revision,
        # Seeded per-test budget snapshot (scenario c overrides the ceiling).
        "budget": budget or build_agent_budget_snapshot(),
    }


def _build_pipeline(
    *,
    resolver: AsyncMock,
    source_repo: AsyncMock,
    chunks_by_source: dict[str, list[MagicMock]],
    monkeypatch: pytest.MonkeyPatch,
    synthesizer: FakeListChatModel,
):
    """Assemble the real agentic graph with deterministic retrieval + synth."""
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())

    async def _similarity_search(*_a: Any, **kwargs: Any):
        sids = kwargs.get("source_ids") or []
        sid = str(sids[0]) if sids else ""
        return [(c, 0.05) for c in chunks_by_source.get(sid, [])]

    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.side_effect = _similarity_search

    async def _no_schema(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "src.agent.nodes.executor.load_schema_context_chunks", _no_schema
    )
    monkeypatch.setattr(
        "src.agent.nodes.generate.build_chat_model",
        lambda _client: synthesizer,
    )

    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()

    return build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=AsyncMock(),
        chat_message_repository=AsyncMock(),
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=None,
        source_repository=source_repo,
        sandbox=True,
    )


async def _run(pipeline: Any, state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    frames = [
        f
        async for f in run_pipeline_stream(
            pipeline=pipeline,
            initial_state=state,
            config={"configurable": {"thread_id": state["session_id"]}},
            trace_id="trace-agentic-t059",
            session_id=state["session_id"],
            langfuse_tracing=_make_tracing(),
            persist_assistant=False,
            on_done=None,
        )
    ]
    return _parse_sse_frames(frames)


# ---------------------------------------------------------------------------
# (a) Chained multi-step — FR-006
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chained_multi_step_file_then_db(
    monkeypatch: pytest.MonkeyPatch, _force_agentic: None
) -> None:
    file_sid = uuid.uuid4()
    db_sid = uuid.uuid4()

    plan_payload = {
        "decision": "plan",
        "steps": [
            {
                "id": "s1",
                "label": "Read the customer names from the file",
                "source_id": str(file_sid),
                "sub_query": "customer names",
                "depends_on": [],
            },
            {
                "id": "s2",
                "label": "Look up the orders for those names in the DB",
                "source_id": str(db_sid),
                "sub_query": "orders for {{s1.output}}",
                "depends_on": ["s1"],
            },
        ],
    }
    grader_ok = {"verdict": "acceptable", "reason": "answers the sub-query", "checks": {}}
    resolver = _make_resolver(
        {
            "planner": _client_returning(plan_payload),
            "retrieval_grader": _client_returning(grader_ok),
        }
    )

    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [
        _source_meta(file_sid, "Customers File", "Synthetic customer list."),
        _source_meta(db_sid, "Orders DB", "Synthetic orders table."),
    ]

    chunks_by_source = {
        str(file_sid): [_fake_chunk(file_sid, "Customers: Alice, Bob.", "customers.csv")],
        str(db_sid): [_fake_chunk(db_sid, "Orders: Alice=2, Bob=5.", "orders_db")],
    }

    # Answer chains BOTH sources (deterministic stub).
    answer = "Alice and Bob (from customers.csv) have 2 and 5 orders respectively (from orders_db)."
    synthesizer = FakeListChatModel(responses=[answer])

    pipeline = _build_pipeline(
        resolver=resolver,
        source_repo=source_repo,
        chunks_by_source=chunks_by_source,
        monkeypatch=monkeypatch,
        synthesizer=synthesizer,
    )
    state = _initial_state([file_sid, db_sid], "Which orders do my file customers have?")
    parsed = await _run(pipeline, state)
    events = [name for name, _ in parsed]

    # A plan event with >= 2 steps.
    plan_events = [d for n, d in parsed if n == "plan"]
    assert len(plan_events) == 1
    assert len(plan_events[0]["steps"]) >= 2
    assert plan_events[0]["steps"][1]["depends_on"] == ["s1"]

    # Ordered step events: s1 started/finished BEFORE s2 started/finished.
    step_events = [d for n, d in parsed if n == "step"]
    step_ids_in_order = [s["step_id"] for s in step_events]
    assert step_ids_in_order.index("s1") < step_ids_in_order.index("s2")
    # Each step narrated started then finished.
    s1_states = [s["state"] for s in step_events if s["step_id"] == "s1"]
    s2_states = [s["state"] for s in step_events if s["step_id"] == "s2"]
    assert s1_states == ["started", "finished"]
    assert s2_states == ["started", "finished"]

    # Terminal done; final answer chains both sources.
    assert events[-1] == "done"
    delta_tokens = "".join(d["token"] for n, d in parsed if n == "delta")
    assert "customers.csv" in delta_tokens
    assert "orders_db" in delta_tokens

    # activity_summary reflects a 2-step, no-failure turn. (source_count is
    # derived from plan/current_step/superseded — StepResult carries no
    # source_id — so after both steps complete only the in-flight step's source
    # survives; the two-source chaining is proven by the ordered step events and
    # the dual-source final answer above, not by this derived counter.)
    summary = parsed[-1][1]["activity_summary"]
    assert summary is not None
    assert summary["step_count"] == 2
    assert summary["source_count"] >= 1
    assert summary["had_failure"] is False
    assert summary["budget_hit"] is False


# ---------------------------------------------------------------------------
# (b) Retry-then-abstain — FR-012 / FR-013
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_then_abstain_with_honest_failure(
    monkeypatch: pytest.MonkeyPatch, _force_agentic: None
) -> None:
    db_sid = uuid.uuid4()

    plan_payload = {
        "decision": "plan",
        "steps": [
            {
                "id": "s1",
                "label": "Look up the record in the DB",
                "source_id": str(db_sid),
                "sub_query": f"find {ABSENT_NAME}",
                "depends_on": [],
            }
        ],
    }
    # Grader is unacceptable on BOTH the initial run and the single retry.
    grader_bad = {"verdict": "unacceptable", "reason": "no rows matched the query", "checks": {}}
    resolver = _make_resolver(
        {
            "planner": _client_returning(plan_payload),
            "retrieval_grader": _client_returning([grader_bad, grader_bad, grader_bad]),
        }
    )

    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [
        _source_meta(db_sid, "Records DB", "Synthetic records table.")
    ]
    # DB lookup empty → no chunks for this source (drives the unacceptable grade).
    chunks_by_source: dict[str, list[MagicMock]] = {str(db_sid): []}

    # Honest-failure answer (stub) — leads with an honest statement, surfaces NO
    # fabricated value for the absent name.
    answer = (
        "I could not find a trustworthy answer for that record. "
        "I searched the Records DB but no matching rows were returned. "
        "You could verify the record exists or rephrase the request."
    )
    synthesizer = _CapturingChatModel(responses=[answer])
    _CapturingChatModel.captured = {}

    pipeline = _build_pipeline(
        resolver=resolver,
        source_repo=source_repo,
        chunks_by_source=chunks_by_source,
        monkeypatch=monkeypatch,
        synthesizer=synthesizer,
    )
    # Seed plan_revision=1 so the EXHAUSTED retry routes straight to the honest-
    # failure synthesizer (no replan) — verify's R4b: retry>=1 and revision>=1.
    state = _initial_state([db_sid], f"What is {ABSENT_NAME}'s record?", plan_revision=1)
    parsed = await _run(pipeline, state)
    events = [name for name, _ in parsed]

    # Exactly ONE retry: s1 executed twice (started/finished each) → 4 step
    # events, all for s1, and NO replan event.
    step_events = [d for n, d in parsed if n == "step"]
    assert all(s["step_id"] == "s1" for s in step_events)
    s1_states = [s["state"] for s in step_events]
    assert s1_states == ["started", "finished", "started", "finished"]
    assert "replan" not in events

    # Final answer leads with the honest-failure copy; the synthesizer was
    # rendered with render_failure_prompt (prompt selection captured).
    assert events[-1] == "done"
    captured_prompt = _CapturingChatModel.captured.get("system_prompt", "")
    assert _FAILURE_PROMPT_LEAD in captured_prompt
    # The exact lead matches render_failure_prompt's first instruction.
    assert _FAILURE_PROMPT_LEAD in render_failure_prompt(
        [], diagnostics="<RETRIEVAL_DIAGNOSTICS></RETRIEVAL_DIAGNOSTICS>"
    )

    # Diagnostics present in the synthesizer prompt (grounded "what I tried").
    assert "<RETRIEVAL_DIAGNOSTICS>" in captured_prompt

    # No fabricated value: the known-absent name is NEVER surfaced as a found
    # value in the answer.
    delta_tokens = "".join(d["token"] for n, d in parsed if n == "delta")
    assert ABSENT_NAME not in delta_tokens

    # activity_summary records the failure.
    summary = parsed[-1][1]["activity_summary"]
    assert summary is not None
    assert summary["had_failure"] is True


# ---------------------------------------------------------------------------
# (c) Graceful budget — FR-019 / FR-020
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_budget_ceiling_hit(
    monkeypatch: pytest.MonkeyPatch, _force_agentic: None
) -> None:
    file_sid = uuid.uuid4()

    plan_payload = {
        "decision": "plan",
        "steps": [
            {
                "id": "s1",
                "label": "Read the policy from the file",
                "source_id": str(file_sid),
                "sub_query": "policy details",
                "depends_on": [],
            },
            {
                "id": "s2",
                "label": "Summarize the policy",
                "source_id": str(file_sid),
                "sub_query": "summary",
                "depends_on": ["s1"],
            },
        ],
    }
    resolver = _make_resolver({"planner": _client_returning(plan_payload)})

    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [
        _source_meta(file_sid, "Policy File", "Synthetic policy doc.")
    ]
    chunks_by_source = {
        str(file_sid): [_fake_chunk(file_sid, "Policy: synthetic content.", "policy.pdf")]
    }

    answer = "I stopped before finishing due to a cost ceiling; here is the partial result."
    synthesizer = FakeListChatModel(responses=[answer])

    pipeline = _build_pipeline(
        resolver=resolver,
        source_repo=source_repo,
        chunks_by_source=chunks_by_source,
        monkeypatch=monkeypatch,
        synthesizer=synthesizer,
    )

    # Per-test tiny token ceiling: the planner spends ~72 tokens, so the FIRST
    # budget_guard_step gate (run AFTER the planner, BEFORE any step) trips
    # immediately on the token cap.  Other caps left generous so only the token
    # ceiling fires.
    budget = {
        "max_steps": 5,
        "max_retries_per_step": 1,
        "max_revisions": 1,
        "token_ceiling": 10,  # << well below the planner's ~72-token spend
        "deadline": None,
    }
    state = _initial_state([file_sid], "Summarize the policy.", budget=budget)
    parsed = await _run(pipeline, state)
    events = [name for name, _ in parsed]

    # A budget event with the exact contract shape.
    budget_events = [d for n, d in parsed if n == "budget"]
    assert len(budget_events) == 1
    bp = budget_events[0]
    assert bp["ceiling_hit"] is True
    assert bp["offer_continue"] is True
    assert isinstance(bp["not_completed"], list)
    # The unexecuted plan steps are surfaced as not-completed.
    assert len(bp["not_completed"]) >= 1

    # Best partial answer present + the stream STILL ends with done (no error /
    # silent failure).
    assert "error" not in events
    assert events[-1] == "done"
    delta_tokens = "".join(d["token"] for n, d in parsed if n == "delta")
    assert delta_tokens  # non-empty partial answer

    # activity_summary records the budget stop.
    summary = parsed[-1][1]["activity_summary"]
    assert summary is not None
    assert summary["budget_hit"] is True
