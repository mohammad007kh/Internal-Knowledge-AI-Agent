"""Integration regression for C1 (T-058): a revised plan is actually dispatched
after a successful replan — the stale superseded step is NOT silently re-run.

This drives the REAL assembled agentic graph (``build_pipeline(sandbox=True)``
with ``PIPELINE_AGENTIC_ENABLED`` forced on) through the FULL failure→retry→
replan→success cycle::

    planner          → 1-step plan [s1]
    execute_step(s1) → retrieves a chunk
    verify_step      → unacceptable (retry 0<1)  → route execute_step
    execute_step(s1) → re-run (pending retry)
    verify_step      → unacceptable (retry 1, plan_revision 0<1) → route replan
    replan           → revised plan [s2]  (success delta clears current_step)
    advance_step     → promotes s2 (NOT the stale s1)
    execute_step(s2) → retrieves a chunk
    verify_step      → acceptable          → route synthesize
    generate_response→ final answer; END

The bug (C1): the replan SUCCESS delta did not clear ``current_step``, so the
stale s1 (retry_count=1) lingered. ``_advance_step`` saw ``_is_pending_retry``
True and re-ran the OLD s1, never dispatching the revised s2 — the whole replan
revision was discarded and the verifier then routed to honest-failure.

This test FAILS without the replan.py fix (s2 is never executed and the turn
ends without a grounded answer) and PASSES with it. A focused companion test
also asserts ``_advance_step`` promotes the revised plan when current_step is
None.

Synthetic-only stubs (public repo): model "test-model-stub", data_source
"synthetic"; deterministic (no real LLM, no real DB).
"""

from __future__ import annotations

import json
import os
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
from langchain_core.messages import HumanMessage  # noqa: E402

from src.agent import pipeline as pipeline_mod  # noqa: E402
from src.agent.pipeline import (  # noqa: E402
    _advance_step,
    build_agent_budget_snapshot,
    build_pipeline,
)
from src.services.ai_model_resolver import AIModelClient  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic plan / grader payloads
# ---------------------------------------------------------------------------

_SOURCE_ID = str(uuid.uuid4())

# The planner stage slot is reused by BOTH planner and replan. Its create()
# returns the initial plan on the 1st call and the REVISED plan on the 2nd.
_INITIAL_PLAN = {
    "decision": "plan",
    "steps": [
        {
            "id": "s1",
            "label": "List the original thing",
            "source_id": _SOURCE_ID,
            "sub_query": "list the original thing",
            "depends_on": [],
        }
    ],
}
_REVISED_PLAN = {
    "decision": "plan",
    "steps": [
        {
            "id": "s2",
            "label": "List the revised thing",
            "source_id": _SOURCE_ID,
            "sub_query": "list the revised thing",
            "depends_on": [],
        }
    ],
}

_UNACCEPTABLE = {"verdict": "unacceptable", "reason": "no rows; broaden the filter", "checks": {}}
_ACCEPTABLE = {"verdict": "acceptable", "reason": "answers the sub-query", "checks": {}}


def _completion(content: str, in_tok: int = 10, out_tok: int = 5) -> MagicMock:
    c = MagicMock()
    c.choices = [MagicMock()]
    c.choices[0].message.content = content
    c.usage.prompt_tokens = in_tok
    c.usage.completion_tokens = out_tok
    return c


def _seq_client(payloads: list[dict[str, Any]]) -> AsyncMock:
    """A stage http_client whose create() returns each payload in turn (then repeats last)."""
    client = AsyncMock()
    completions = [_completion(json.dumps(p)) for p in payloads]
    holder = {"i": 0}

    async def _create(*_a: Any, **_kw: Any) -> MagicMock:
        i = min(holder["i"], len(completions) - 1)
        holder["i"] += 1
        return completions[i]

    client.chat.completions.create.side_effect = _create
    return client


def _messages_text(kwargs: dict[str, Any]) -> str:
    """Flatten the messages content passed to chat.completions.create."""
    parts: list[str] = []
    for m in kwargs.get("messages") or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _content_keyed_grader() -> AsyncMock:
    """Grader keyed by sub_query CONTENT, not call order.

    Returns ``acceptable`` ONLY when the prompt carries the REVISED sub_query;
    every original-step grading is ``unacceptable``. This makes the regression
    deterministic regardless of how many times the (buggy) graph re-runs the old
    step: only the revised step can ever be graded acceptable, so the turn can
    only succeed if s2 is actually dispatched.
    """
    client = AsyncMock()
    ok = _completion(json.dumps(_ACCEPTABLE))
    bad = _completion(json.dumps(_UNACCEPTABLE))

    async def _create(*_a: Any, **kwargs: Any) -> MagicMock:
        return ok if "revised thing" in _messages_text(kwargs) else bad

    client.chat.completions.create.side_effect = _create
    return client


def _make_resolver(stage_clients: dict[str, AsyncMock]) -> AsyncMock:
    resolver = AsyncMock()

    async def _resolve(stage: str) -> AIModelClient:
        # Any unrequested stage (e.g. the synthesizer, whose chat model is
        # patched via build_chat_model) gets a generic stub client.
        http_client = stage_clients.get(stage) or _seq_client([{}])
        return AIModelClient(
            ai_model_id=uuid.uuid4(),
            provider="openai",
            model_id="test-model-stub",
            temperature=0.0,
            max_tokens=512,
            custom_prompt=None,
            capabilities={},
            http_client=http_client,
        )

    resolver.resolve.side_effect = _resolve
    return resolver


def _build_replan_pipeline(monkeypatch: pytest.MonkeyPatch):
    """Assemble the real agentic graph wired for the retry→replan→success cycle."""
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_AGENTIC_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_V2_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_REFLECTOR_ENABLED", False)
    # Caps: 1 retry per step, 1 plan revision — the exact window this bug lives in.
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_PLAN_STEPS", 5)
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_STEP_RETRIES", 1)
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_PLAN_REVISIONS", 1)
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_TOKEN_CEILING_INPUT", 1_000_000)
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_TOKEN_CEILING_OUTPUT", 1_000_000)
    monkeypatch.setattr(pipeline_mod.settings, "AGENT_TURN_DEADLINE_SECS", None)

    # planner slot: initial plan, then revised plan on the replan call.
    planner_client = _seq_client([_INITIAL_PLAN, _REVISED_PLAN])
    # retrieval_grader slot: ONLY the revised sub_query grades acceptable, so the
    # turn can only succeed if the revised step is genuinely dispatched.
    grader_client = _content_keyed_grader()
    resolver = _make_resolver(
        {"planner": planner_client, "retrieval_grader": grader_client}
    )

    # source_meta_loader → SourceRepository.list_by_ids returns one permitted source.
    src = MagicMock()
    src.id = uuid.UUID(_SOURCE_ID)
    src.name = "Synthetic Source A"
    src.purpose = "Synthetic purpose."
    src.example_questions = ["Example?"]
    src.out_of_scope = ["PII"]
    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [src]

    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())

    chunk = MagicMock()
    chunk.id = "chunk-1"
    chunk.source_id = _SOURCE_ID
    chunk.chunk_text = "Synthetic chunk text."
    chunk.metadata_ = {"document_title": "Doc.pdf", "page_number": 1, "source_name": "Synthetic Source A"}
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = [(chunk, 0.05)]

    async def _no_schema(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("src.agent.nodes.executor.load_schema_context_chunks", _no_schema)
    monkeypatch.setattr(
        "src.agent.nodes.generate.build_chat_model",
        lambda _client: FakeListChatModel(responses=["The revised answer."]),
    )

    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()

    pipeline = build_pipeline(
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
    return pipeline, planner_client, grader_client


def _initial_state(query: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=query)],
        "source_ids": [_SOURCE_ID],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": str(uuid.uuid4()),
        "user_id": "user-1",
        "trace_id": "trace-replan-c1",
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
        "plan_revision": 0,
        "data_source": "synthetic",
        "budget": build_agent_budget_snapshot(),
    }


# ---------------------------------------------------------------------------
# C1 — end-to-end: the revised step is dispatched, not the stale s1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revised_plan_is_dispatched_after_replan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revised step (s2) is actually executed and the turn terminates with a
    grounded answer — the stale s1 is NOT silently re-run after the replan.
    """
    pipeline, planner_client, grader_client = _build_replan_pipeline(monkeypatch)
    state = _initial_state("Find the revised thing")

    result = await pipeline.ainvoke(
        state, config={"configurable": {"thread_id": state["session_id"]}}
    )

    past_steps = result.get("past_steps") or []
    executed_step_ids = [p.get("step_id") for p in past_steps]

    # The revised step s2 MUST have executed (this is what the bug dropped).
    assert "s2" in executed_step_ids, (
        "revised step s2 was never dispatched — the replan revision was discarded "
        f"(executed steps: {executed_step_ids})"
    )
    # The s2 result must be acceptable (the success path that synthesizes).
    s2_results = [p for p in past_steps if p.get("step_id") == "s2"]
    assert s2_results, "no StepResult recorded for the revised step s2"
    assert (s2_results[-1].get("verification") or {}).get("verdict") == "acceptable"

    # A whole revision was spent (FR-007); superseded_plan is retained as the
    # remaining (un-dispatched) plan at replan time — empty here because the lone
    # original step was already in-flight (current_step) when replan ran (FR-008).
    assert result.get("plan_revision") == 1
    assert "superseded_plan" in result

    # The turn terminated on the SUCCESS path (grounded answer), NOT honest-failure.
    assert result.get("final_answer")
    assert not result.get("_synthesize_failure")
    assert not result.get("budget_hit")

    # Sanity: planner slot called twice (plan + replan). The grader is keyed by
    # content, so only the revised step's grading can be acceptable.
    assert planner_client.chat.completions.create.await_count == 2
    assert grader_client.chat.completions.create.await_count >= 3


# ---------------------------------------------------------------------------
# Focused: _advance_step promotes the revised plan when current_step is None
# ---------------------------------------------------------------------------


def test_advance_step_promotes_revised_plan_when_current_step_none() -> None:
    """After the replan fix clears current_step, _advance_step pops the revised
    plan's first step (the dispatch glue that the C1 fix re-enables).
    """
    revised_step = {
        "id": "s2",
        "description": "List the revised thing",
        "source_id": _SOURCE_ID,
        "sub_query": "list the revised thing",
        "depends_on": [],
        "status": "pending",
        "retry_count": 0,
    }
    state: dict[str, Any] = {
        "plan": [revised_step],
        "current_step": None,  # cleared by the replan success delta
        # A stale s1 unacceptable result lingers in history — must NOT cause a re-run.
        "past_steps": [
            {
                "step_id": "s1",
                "output_chunks": [],
                "generated_sql": None,
                "bound_inputs": None,
                "verification": {"verdict": "unacceptable", "reason": "no rows", "checks": {}},
                "narration": "",
            }
        ],
    }

    delta = _advance_step(state)

    assert delta.get("current_step") == revised_step
    assert delta.get("plan") == []


def test_advance_step_would_drop_revision_if_stale_step_lingered() -> None:
    """Documents the bug contract: a lingering stale retry step (the pre-fix
    state) makes _advance_step a no-op, so the revised plan is never dispatched.

    This is the precise failure the replan.py current_step=None clear prevents.
    """
    stale_s1 = {
        "id": "s1",
        "description": "Old step",
        "source_id": _SOURCE_ID,
        "sub_query": "[Retry context: ...]\nlist the original thing",
        "depends_on": [],
        "status": "failed",
        "retry_count": 1,  # verifier-issued retry
    }
    revised_step = {
        "id": "s2",
        "description": "List the revised thing",
        "source_id": _SOURCE_ID,
        "sub_query": "list the revised thing",
        "depends_on": [],
        "status": "pending",
        "retry_count": 0,
    }
    state: dict[str, Any] = {
        "plan": [revised_step],
        "current_step": stale_s1,  # the pre-fix lingering step
        "past_steps": [
            {
                "step_id": "s1",
                "output_chunks": [],
                "generated_sql": None,
                "bound_inputs": None,
                "verification": {"verdict": "unacceptable", "reason": "no rows", "checks": {}},
                "narration": "",
            }
        ],
    }

    delta = _advance_step(state)

    # No-op: the stale retry is treated as pending → the revised s2 is NOT promoted.
    assert delta == {}
