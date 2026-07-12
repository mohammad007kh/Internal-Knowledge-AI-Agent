"""LangGraph pipeline — v1 (legacy) and v2 (full 5-node) builders.

The active topology is selected by ``settings.PIPELINE_V2_ENABLED``:

* **v1** (legacy):  load_history → check_clarification(heuristic) →
  guardrail_input → retrieve_context → generate_response →
  format_response → guardrail_output → END
* **v2** (default): load_history → guardrail_input →
  check_clarification(LLM) → query_analyzer → source_router →
  (retrieve_context | text_to_query) → generate_response →
  [reflector → optional retry] → format_response → guardrail_output → END

Both share the same compiled-graph signature so callers do not need to
know which one is wired in — the env-flag rollback is a 30-second
backend restart away.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.budget_guard import budget_guard
from src.agent.nodes import (
    analyze_query,
    check_clarification,
    execute_step,
    format_response,
    generate_response,
    guardrail_input,
    guardrail_output,
    handle_clarification,
    load_history,
    plan_query,
    reflect,
    replan_step,
    retrieve_context,
    route_after_verify,
    route_sources,
    text_to_query,
    verify_step,
)
from src.agent.state import AgentState, PlanStep
from src.core.config import settings
from src.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from src.repositories.chunk_repository import ChunkRepository
from src.repositories.source_repository import SourceRepository
from src.services.ai_model_resolver import AIModelResolver
from src.services.embedding_service_factory import EmbeddingServiceFactory
from src.services.guardrail_service import GuardrailService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routers — shared between v1 and v2 graphs
# ---------------------------------------------------------------------------


def _route_after_clarify(state: AgentState) -> str:
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "continue"


def _route_after_guardrail_input(state: AgentState) -> str:
    """Short-circuit to END when the input guardrail blocks the query."""
    if state.get("error") == "guardrail_blocked_input":
        return END
    return "continue"


def _route_after_router(state: AgentState) -> str:
    """Decide whether to fan out into text_to_query or skip directly to retrieve.

    Both branches are always run sequentially so the synthesizer sees
    chunks from each.  We only branch *off* text_to_query when no source
    was routed there to avoid an unnecessary LLM call.
    """
    if state.get("text_to_query_source_ids"):
        return "text_to_query"
    return "retrieve_context"


def _route_after_reflect(state: AgentState) -> str:
    """Re-loop into query_analyzer when the reflector flagged a retry."""
    if state.get("reflector_feedback"):
        return "query_analyzer"
    return "format_response"


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None = None,
    source_repository: SourceRepository | None = None,
    sandbox: bool = False,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the active pipeline.

    Selection order (FR-026, sandbox-first):

    * **agentic** — when ``settings.PIPELINE_AGENTIC_ENABLED`` is True AND this
      is the *sandbox* path (``sandbox=True``) AND a *source_repository* is
      available.  Plan-and-execute graph with hard caps at the loop edges; the
      v2 graph remains the exact rollback (flip the flag and restart). Guardrail
      input/output wrap it unconditionally (Constitution IV); the reflector is
      NOT inserted.
    * **v2** — when ``settings.PIPELINE_V2_ENABLED`` is True (requires
      *source_repository*; pass-through to v1 when missing).
    * **v1** — legacy single-shot, kept verbatim for emergency rollback.

    The agentic path is gated on ``sandbox`` so general chat keeps the proven v2
    topology until the eval gates pass (FR-026); both endpoints share this
    builder via the DI container but the sandbox endpoint requests
    ``sandbox=True``.
    """
    if (
        settings.PIPELINE_AGENTIC_ENABLED
        and sandbox
        and source_repository is not None
    ):
        logger.info(
            "pipeline: building agentic (PIPELINE_AGENTIC_ENABLED=True, sandbox=True)"
        )
        return _build_agentic_pipeline(
            db_session=db_session,
            chunk_repository=chunk_repository,
            chat_session_repository=chat_session_repository,
            chat_message_repository=chat_message_repository,
            ai_model_resolver=ai_model_resolver,
            embedding_service_factory=embedding_service_factory,
            langfuse=langfuse,
            guardrail_service=guardrail_service,
            source_repository=source_repository,
        )
    if settings.PIPELINE_V2_ENABLED and source_repository is not None:
        logger.info("pipeline: building v2 (PIPELINE_V2_ENABLED=True)")
        return _build_v2_pipeline(
            db_session=db_session,
            chunk_repository=chunk_repository,
            chat_session_repository=chat_session_repository,
            chat_message_repository=chat_message_repository,
            ai_model_resolver=ai_model_resolver,
            embedding_service_factory=embedding_service_factory,
            langfuse=langfuse,
            guardrail_service=guardrail_service,
            source_repository=source_repository,
        )
    logger.info(
        "pipeline: building v1 (PIPELINE_V2_ENABLED=%s, source_repository=%s)",
        settings.PIPELINE_V2_ENABLED,
        "set" if source_repository is not None else "missing",
    )
    return _build_v1_pipeline(
        db_session=db_session,
        chunk_repository=chunk_repository,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        ai_model_resolver=ai_model_resolver,
        embedding_service_factory=embedding_service_factory,
        langfuse=langfuse,
        guardrail_service=guardrail_service,
    )


# ---------------------------------------------------------------------------
# v1 — legacy single-shot pipeline (rollback target)
# ---------------------------------------------------------------------------


def _build_v1_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    # Note: ``StateGraph`` is not generic-subscriptable in the installed
    # langgraph version (``TypeError: type 'StateGraph' is not subscriptable``).
    # The function annotation above already documents the state type — the
    # variable annotation alone is sufficient to keep static analyzers happy.
    workflow: StateGraph = StateGraph(AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    # v1 uses the heuristic-only path — no resolver passed.
    _check_clarification = functools.partial(
        check_clarification,
        langfuse=langfuse,
    )
    _retrieve_context = functools.partial(
        retrieve_context,
        embedding_service_factory=embedding_service_factory,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    _generate_response = functools.partial(
        generate_response,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )

    workflow.add_node("load_history", _load_history)
    workflow.add_node("check_clarification", _check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    if guardrail_service is not None:
        workflow.add_node(
            "guardrail_input",
            functools.partial(
                guardrail_input,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
        workflow.add_node(
            "guardrail_output",
            functools.partial(
                guardrail_output,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )

    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        _route_after_clarify,
        {
            "handle_clarification": "handle_clarification",
            "continue": "guardrail_input" if guardrail_service is not None else "retrieve_context",
        },
    )
    # Route the clarification text through guardrail_output so it gets
    # the same content-policy check as a normal answer.
    if guardrail_service is not None:
        workflow.add_edge("handle_clarification", "guardrail_output")
    else:
        workflow.add_edge("handle_clarification", END)

    if guardrail_service is not None:
        workflow.add_conditional_edges(
            "guardrail_input",
            _route_after_guardrail_input,
            {
                END: END,
                "continue": "retrieve_context",
            },
        )

    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", "format_response")

    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# v2 — full pipeline with the 5 newly-wired LLM nodes
# ---------------------------------------------------------------------------


def _build_v2_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None,
    source_repository: SourceRepository,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    # See note in :func:`_build_v1_pipeline` — drop the generic subscript;
    # the installed langgraph version does not support it.
    workflow: StateGraph = StateGraph(AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    _check_clarification = functools.partial(
        check_clarification,
        langfuse=langfuse,
        ai_model_resolver=ai_model_resolver,
    )
    _analyze_query = functools.partial(
        analyze_query,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    _route_sources = functools.partial(
        route_sources,
        ai_model_resolver=ai_model_resolver,
        db_session=db_session,
        source_repository=source_repository,
        langfuse=langfuse,
    )
    _retrieve_context = functools.partial(
        retrieve_context,
        embedding_service_factory=embedding_service_factory,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    _text_to_query = functools.partial(
        text_to_query,
        ai_model_resolver=ai_model_resolver,
        db_session=db_session,
        source_repository=source_repository,
        langfuse=langfuse,
    )
    _generate_response = functools.partial(
        generate_response,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    reflector_enabled = bool(settings.PIPELINE_REFLECTOR_ENABLED)
    # Clarifier is OFF by default. The "references entities not yet
    # introduced" rule fires on virtually every fresh query in a RAG system,
    # short-circuiting retrieve_context before it ever runs. Letting retrieve
    # be the gate (returns 0 chunks → synthesizer says "I don't have info")
    # is a better UX. Re-enable per-environment via PIPELINE_CLARIFY_ENABLED.
    clarify_enabled = bool(settings.PIPELINE_CLARIFY_ENABLED)
    _reflect = functools.partial(
        reflect,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
        max_retries=int(settings.PIPELINE_REFLECTOR_MAX_RETRIES),
    )

    workflow.add_node("load_history", _load_history)
    if clarify_enabled:
        workflow.add_node("check_clarification", _check_clarification)
        workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("query_analyzer", _analyze_query)
    workflow.add_node("source_router", _route_sources)
    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("text_to_query", _text_to_query)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    if guardrail_service is not None:
        workflow.add_node(
            "guardrail_input",
            functools.partial(
                guardrail_input,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
        workflow.add_node(
            "guardrail_output",
            functools.partial(
                guardrail_output,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
    if reflector_enabled:
        workflow.add_node("reflector", _reflect)

    # Edges -----------------------------------------------------------------
    # Slice E defect-3 fix (V2 ONLY): guardrail_input must run BEFORE
    # check_clarification so a hostile / PII-laden query is blocked before
    # we burn an LLM call deciding whether to clarify it.  V1 keeps its
    # historical order (clarify first) — see _build_v1_pipeline.
    # When clarify is disabled the post-guardrail edge skips straight to
    # query_analyzer, keeping the rest of the graph identical.
    post_guard_target = "check_clarification" if clarify_enabled else "query_analyzer"

    workflow.add_edge(START, "load_history")
    if guardrail_service is not None:
        workflow.add_edge("load_history", "guardrail_input")
        workflow.add_conditional_edges(
            "guardrail_input",
            _route_after_guardrail_input,
            {
                END: END,
                "continue": post_guard_target,
            },
        )
    else:
        workflow.add_edge("load_history", post_guard_target)
    if clarify_enabled:
        workflow.add_conditional_edges(
            "check_clarification",
            _route_after_clarify,
            {
                "handle_clarification": "handle_clarification",
                "continue": "query_analyzer",
            },
        )
        # Route the clarification text through guardrail_output so it gets
        # the same content-policy check as a normal answer (matches v1).
        if guardrail_service is not None:
            workflow.add_edge("handle_clarification", "guardrail_output")
        else:
            workflow.add_edge("handle_clarification", END)

    workflow.add_edge("query_analyzer", "source_router")
    workflow.add_conditional_edges(
        "source_router",
        _route_after_router,
        {
            "text_to_query": "text_to_query",
            "retrieve_context": "retrieve_context",
        },
    )
    # text_to_query and retrieve_context both feed the synthesizer.  When
    # text_to_query fired we still want vector retrieval for non-DB
    # sources; chain it through retrieve_context next.
    workflow.add_edge("text_to_query", "retrieve_context")
    workflow.add_edge("retrieve_context", "generate_response")

    if reflector_enabled:
        workflow.add_edge("generate_response", "reflector")
        workflow.add_conditional_edges(
            "reflector",
            _route_after_reflect,
            {
                "query_analyzer": "query_analyzer",
                "format_response": "format_response",
            },
        )
    else:
        workflow.add_edge("generate_response", "format_response")

    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# agentic — plan-and-execute graph (004; assembled from T-052..T-057)
# ---------------------------------------------------------------------------


def build_agent_budget_snapshot() -> dict[str, Any]:
    """Build the read-only per-turn budget snapshot from settings (FR-007/FR-019).

    Maps the operator-controlled caps to the ``_AgentBudget`` contract the
    deterministic guard (T-057) reads at every loop edge:

    * ``max_steps``            ← ``AGENT_MAX_PLAN_STEPS``
    * ``max_retries_per_step`` ← ``AGENT_MAX_STEP_RETRIES``
    * ``max_revisions``        ← ``AGENT_MAX_PLAN_REVISIONS``
    * ``token_ceiling``        ← ``AGENT_TOKEN_CEILING_INPUT + AGENT_TOKEN_CEILING_OUTPUT``
      (the guard compares against combined input+output spend)
    * ``deadline``             ← ISO-8601 absolute time ``now + AGENT_TURN_DEADLINE_SECS``,
      or ``None`` when the wall-clock guard is disabled.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    deadline: str | None = None
    secs = settings.AGENT_TURN_DEADLINE_SECS
    if isinstance(secs, int) and secs > 0:
        deadline = (datetime.now(UTC) + timedelta(seconds=secs)).isoformat()
    return {
        "max_steps": int(settings.AGENT_MAX_PLAN_STEPS),
        "max_retries_per_step": int(settings.AGENT_MAX_STEP_RETRIES),
        "max_revisions": int(settings.AGENT_MAX_PLAN_REVISIONS),
        "token_ceiling": int(settings.AGENT_TOKEN_CEILING_INPUT)
        + int(settings.AGENT_TOKEN_CEILING_OUTPUT),
        "deadline": deadline,
    }


def _make_source_meta_loader(
    *,
    db_session: AsyncSession,
    source_repository: SourceRepository,
) -> Any:
    """Build the planner/replan ``source_meta_loader`` over the real DB.

    Contract (mirrors the planner/replan unit-test fixtures): an async callable
    ``(source_ids: list[str]) -> list[dict]`` where each dict carries
    ``id`` / ``name`` / ``purpose`` / ``examples`` / ``out_of_scope``.  The
    Source ORM stores ``example_questions`` (list) and ``out_of_scope`` (list);
    we render them to short strings for the prompt block (Security Rule 1: data,
    never instructions).  Unknown / inaccessible ids are simply absent from the
    result (the planner asserts ``source_id ⊆ permitted_set`` afterwards).
    """
    import uuid as _uuid  # noqa: PLC0415

    async def _loader(source_ids: list[str]) -> list[dict[str, Any]]:
        if not source_ids:
            return []
        parsed: list[_uuid.UUID] = []
        for sid in source_ids:
            try:
                parsed.append(_uuid.UUID(str(sid)))
            except (ValueError, TypeError):
                continue
        rows = await source_repository.list_by_ids(parsed)
        out: list[dict[str, Any]] = []
        for row in rows:
            examples = row.example_questions or []
            scope = row.out_of_scope or []
            out.append(
                {
                    "id": str(row.id),
                    "name": row.name or "",
                    "purpose": row.purpose or "",
                    "examples": "; ".join(str(e) for e in examples) if isinstance(examples, list) else str(examples),
                    "out_of_scope": "; ".join(str(s) for s in scope) if isinstance(scope, list) else str(scope),
                }
            )
        return out

    return _loader


def _route_after_planner(state: AgentState) -> str:
    """planner → clarification-terminal | honest-failure | dispatch the first step."""
    if state.get("requires_clarification"):
        return "handle_clarification"
    if state.get("error") or not (state.get("plan") or []):
        # Planner failed / permission violation / empty plan → honest failure.
        return "synthesize_failure"
    return "continue"


def _is_pending_retry(state: AgentState) -> bool:
    """True when ``current_step`` is a verifier-issued retry awaiting re-execution.

    The verifier (T-054 ``_build_verify_delta``) only writes a NEW
    ``current_step`` (with ``retry_count`` incremented and a canned hint
    prefixed onto ``sub_query``) on the unacceptable-retry branch — the
    success/next-step branch leaves ``current_step`` pointing at the just-
    completed step.  So a ``current_step`` whose ``retry_count > 0`` and whose
    latest matching ``past_steps`` verdict is NOT acceptable/partial is a retry
    that must be RE-EXECUTED as-is, never overwritten by the next plan step.
    """
    current = state.get("current_step")
    if not isinstance(current, dict) or int(current.get("retry_count", 0)) <= 0:
        return False
    step_id = current.get("id")
    for entry in reversed(state.get("past_steps") or []):
        if isinstance(entry, dict) and entry.get("step_id") == step_id:
            verdict = (entry.get("verification") or {}).get("verdict")
            return verdict not in ("acceptable", "partial")
    # No recorded result yet for this retry step → it is awaiting execution.
    return True


def _advance_step(state: AgentState) -> dict[str, Any]:
    """Dispatch the next executor step (T-058 dispatch glue).

    The plan-and-execute convention (mirrored by the executor/verify nodes and
    their unit tests): ``plan`` holds the steps NOT yet dispatched and
    ``current_step`` is the in-flight one.

    * **Retry** — when ``current_step`` is a verifier-issued retry awaiting
      re-execution, leave it in place (re-run the SAME step) and do NOT pop the
      plan: overwriting it would skip the retry and silently drop a step.
    * **Next step** — otherwise promote ``plan[0]`` to ``current_step`` and drop
      it from ``plan``.

    Immutability: a new list / dict is returned; the input plan is never mutated.
    """
    if _is_pending_retry(state):
        return {}
    plan: list[PlanStep] = list(state.get("plan") or [])
    if not plan:
        # Nothing to dispatch — the verify/planner routers only send a "next
        # step" here when the plan is non-empty, so this is defence in depth.
        return {}
    nxt = plan[0]
    return {"current_step": nxt, "plan": plan[1:]}


def _agentic_budget_guard(state: AgentState) -> dict[str, Any]:
    """Node wrapper around the pure :func:`budget_guard` (T-057).

    Returns the guard's ``state_delta`` (``budget_hit`` + optional
    ``budget_event_data``) so the downstream conditional edge can route a breach
    to the synthesizer.  The pure function owns all the cap logic; this wrapper
    only surfaces it into the graph (no LLM, no mutation).
    """
    decision = budget_guard(state)
    return dict(decision.state_delta)


def _route_after_budget(state: AgentState) -> str:
    """budget edge: breach → honest synthesize; else continue (dispatch or replan)."""
    if state.get("budget_hit"):
        return "synthesize_failure"
    return "continue"


def _route_after_replan(state: AgentState) -> str:
    """replan → honest-failure on error/empty, else dispatch the revised plan."""
    if state.get("error") or not (state.get("plan") or []):
        return "synthesize_failure"
    return "continue"


def _mark_synthesize_failure(state: AgentState) -> dict[str, Any]:  # noqa: ARG001
    """Flag the upcoming synthesizer run to use the honest-failure prompt (T-057).

    The synthesizer (:func:`generate_response`) reads ``_synthesize_failure`` (or
    ``budget_hit``) to switch from the grounded prompt to
    ``render_failure_prompt`` with the diagnostics block.
    """
    return {"_synthesize_failure": True}


def _build_agentic_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None,
    source_repository: SourceRepository,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble the plan-and-execute agentic graph (FR-026; T-052..T-057).

    Topology::

        START → load_history → [guardrail_input] →
          planner ─┬─(needs_clarification)→ handle_clarification → [guardrail_output] → END
                   ├─(error/empty plan)────→ synthesize_failure
                   └─(plan)────────────────→ budget_guard_step
        budget_guard_step ─┬─(breach)→ synthesize_failure
                           └─(ok)────→ advance_step → execute_step → verify_step
        verify_step ─(route_after_verify: R4b)→
            execute_step→budget_guard_step (next/retry) | replan→budget_guard_replan |
            synthesize→generate_response | synthesize_honest_failure→synthesize_failure
        budget_guard_replan ─┬─(breach)→ synthesize_failure └─(ok)→ replan
        replan ─┬─(error/empty)→ synthesize_failure └─(ok)→ budget_guard_step
        synthesize_failure → generate_response
        generate_response → format_response → [guardrail_output] → END

    Guardrail input/output wrap the WHOLE graph unconditionally (Constitution IV)
    — there is NO bypass path.  The reflector is deliberately NOT inserted
    (default-OFF, untouched).
    """
    workflow: StateGraph = StateGraph(AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    _source_meta_loader = _make_source_meta_loader(
        db_session=db_session,
        source_repository=source_repository,
    )
    _plan_query = functools.partial(
        plan_query,
        langfuse=langfuse,
        ai_model_resolver=ai_model_resolver,
        source_meta_loader=_source_meta_loader,
    )
    _execute_step = functools.partial(
        execute_step,
        langfuse=langfuse,
        embedding_service_factory=embedding_service_factory,
        chunk_repository=chunk_repository,
        db_session=db_session,
    )
    _verify_step = functools.partial(
        verify_step,
        langfuse=langfuse,
        ai_model_resolver=ai_model_resolver,
    )
    _replan_step = functools.partial(
        replan_step,
        langfuse=langfuse,
        ai_model_resolver=ai_model_resolver,
        source_meta_loader=_source_meta_loader,
    )
    _generate_response = functools.partial(
        generate_response,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )

    # --- nodes -------------------------------------------------------------
    # Two budget-gate instances wrap the SAME pure guard (T-057): one BEFORE
    # each step dispatch, one BEFORE replan (FR-019).  Distinct nodes so each
    # can route its "continue" to the right successor (advance vs replan) while
    # a breach in either routes honestly to the synthesizer.
    workflow.add_node("load_history", _load_history)
    workflow.add_node("planner", _plan_query)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("budget_guard_step", _agentic_budget_guard)
    workflow.add_node("budget_guard_replan", _agentic_budget_guard)
    workflow.add_node("advance_step", _advance_step)
    workflow.add_node("execute_step", _execute_step)
    workflow.add_node("verify_step", _verify_step)
    workflow.add_node("replan", _replan_step)
    workflow.add_node("synthesize_failure", _mark_synthesize_failure)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    if guardrail_service is not None:
        workflow.add_node(
            "guardrail_input",
            functools.partial(
                guardrail_input,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
        workflow.add_node(
            "guardrail_output",
            functools.partial(
                guardrail_output,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )

    # --- edges -------------------------------------------------------------
    # Guardrail input wraps the WHOLE graph (Constitution IV — no bypass).
    workflow.add_edge(START, "load_history")
    if guardrail_service is not None:
        workflow.add_edge("load_history", "guardrail_input")
        workflow.add_conditional_edges(
            "guardrail_input",
            _route_after_guardrail_input,
            {END: END, "continue": "planner"},
        )
    else:
        workflow.add_edge("load_history", "planner")

    # planner → clarification | honest-failure | first dispatch (via budget gate)
    workflow.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "handle_clarification": "handle_clarification",
            "synthesize_failure": "synthesize_failure",
            "continue": "budget_guard_step",
        },
    )
    if guardrail_service is not None:
        workflow.add_edge("handle_clarification", "guardrail_output")
    else:
        workflow.add_edge("handle_clarification", END)

    # Step budget gate (BEFORE every step dispatch): breach → honest synthesize;
    # else advance the next pending step + execute.
    workflow.add_conditional_edges(
        "budget_guard_step",
        _route_after_budget,
        {
            "synthesize_failure": "synthesize_failure",
            "continue": "advance_step",
        },
    )
    workflow.add_edge("advance_step", "execute_step")
    workflow.add_edge("execute_step", "verify_step")

    # verify OWNS the R4b conditional edge (route_after_verify). A "next step" or
    # "retry" re-enters the STEP budget gate; "replan" enters the REPLAN budget
    # gate (so the cap is checked before the costly revision); "synthesize" is
    # the success terminal; "synthesize_honest_failure" is the exhausted path.
    workflow.add_conditional_edges(
        "verify_step",
        route_after_verify,
        {
            "execute_step": "budget_guard_step",
            "replan": "budget_guard_replan",
            "synthesize": "generate_response",
            "synthesize_honest_failure": "synthesize_failure",
        },
    )

    # Replan budget gate (BEFORE replan): breach → honest synthesize; else replan.
    workflow.add_conditional_edges(
        "budget_guard_replan",
        _route_after_budget,
        {
            "synthesize_failure": "synthesize_failure",
            "continue": "replan",
        },
    )
    # After a successful revision, dispatch the revised plan's first step through
    # the STEP budget gate again (the loop is re-bounded every iteration).
    workflow.add_conditional_edges(
        "replan",
        _route_after_replan,
        {
            "synthesize_failure": "synthesize_failure",
            "continue": "budget_guard_step",
        },
    )

    # honest-failure / budget wrap-up and success both synthesize then format.
    workflow.add_edge("synthesize_failure", "generate_response")
    workflow.add_edge("generate_response", "format_response")

    # Guardrail output wraps the WHOLE graph (Constitution IV — no bypass).
    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Convenience runner — used by tests.  Production goes via chat.py's
# astream_events directly.
# ---------------------------------------------------------------------------


async def run_pipeline(
    *,
    compiled_graph: CompiledStateGraph[Any, Any, Any, Any],
    session_id: str,
    user_id: str,
    query: str,
    source_ids: list[str],
    trace_id: str,
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage  # noqa: PLC0415

    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    initial_state: AgentState = {
        "messages": [HumanMessage(content=query)],
        "source_ids": source_ids,
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": session_id,
        "user_id": user_id,
        "trace_id": trace_id,
        "query": query,
        "final_answer": None,
        "error": None,
        "sources": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "query_variants": [],
        "selected_source_ids": [],
        "text_to_query_source_ids": [],
        "generated_sql": {},
        "reflector_feedback": None,
        "reflector_retries": 0,
        # --- agentic plan-state seeds (T-058) ------------------------------
        # raw_user_intent is the ORIGINAL utterance — never mutated by any node
        # (query is rewritten by query_analyzer / load_history; this is not).
        "raw_user_intent": query,
        "plan": [],
        "past_steps": [],
        "current_step": None,
        "plan_revision": 0,
        # Read-only budget snapshot — every loop-edge guard reads from here
        # (FR-007/FR-019). No node writes it.
        "budget": build_agent_budget_snapshot(),
    }
    result = await compiled_graph.ainvoke(initial_state, config=config)
    return dict(result)
