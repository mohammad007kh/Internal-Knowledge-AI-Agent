"""AgentState TypedDict for LangGraph pipeline."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class PlanStep(TypedDict):
    """A single step in the agent's execution plan (data-model §2, R1).

    ``sub_query`` may contain ``{{sN.output}}`` references resolved by the
    executor before dispatch.  ``source_id`` is a UUID string (one source per
    step per R1).  ``status`` transitions: pending → active → done | failed.
    """

    id: str
    description: str
    source_id: str  # UUID stored as string
    sub_query: str
    depends_on: list[str]
    status: Literal["pending", "active", "done", "failed"]
    retry_count: int


class _BoundInputs(TypedDict):
    """Records exactly what was interpolated into a sub_query (R1b)."""

    refs: dict[str, str]
    truncated: bool


class _Verification(TypedDict):
    """Per-step verification verdict from the grader node."""

    verdict: Literal["acceptable", "partial", "unacceptable"]
    reason: str
    checks: dict[str, Any]


class StepResult(TypedDict):
    """Output of a single executed step (data-model §2).

    ``output_chunks`` are step-scoped (not merged into turn-wide
    ``retrieved_chunks`` until the synthesizer collects them).
    ``bound_inputs`` is None when the sub_query had no references.
    """

    step_id: str
    output_chunks: list[dict[str, Any]]
    generated_sql: str | None
    bound_inputs: _BoundInputs | None
    verification: _Verification
    narration: str  # ≤ 200 chars; human-readable step summary


class _AgentBudget(TypedDict):
    """Read-only config snapshot injected at graph entry (FR-007/FR-019)."""

    max_steps: int
    max_retries_per_step: int
    max_revisions: int
    token_ceiling: int
    deadline: str | None  # ISO-8601 or None


class AgentState(TypedDict, total=False):
    """Shared state passed through every node in the pipeline.

    ``total=False`` so v2 nodes can omit fields they do not own without
    breaking v1's stricter contract.  Every consumer must guard reads
    with ``state.get(...)``.
    """

    # --- v1 / always-present ------------------------------------------------
    messages: Annotated[list[BaseMessage], add_messages]
    source_ids: list[str]
    retrieved_chunks: list[dict[str, Any]]
    requires_clarification: bool
    clarification_question: str | None
    session_id: str
    user_id: str
    trace_id: str
    query: str
    final_answer: str | None
    error: str | None
    sources: list[dict[str, Any]]
    total_input_tokens: Annotated[int, operator.add]
    total_output_tokens: Annotated[int, operator.add]
    # --- v2 additions -------------------------------------------------------
    query_variants: list[str]
    selected_source_ids: list[str]
    text_to_query_source_ids: list[str]
    generated_sql: dict[str, str]
    reflector_feedback: str | None
    reflector_retries: int
    query_analyzer_degraded: bool
    # --- agentic-pipeline additions (T-051) ---------------------------------
    # raw_user_intent: the original utterance — NEVER mutated by any node.
    # (query is rewritten by query_analyzer / load_history; this field is not.)
    raw_user_intent: str
    plan: list[PlanStep]
    past_steps: list[StepResult]
    current_step: PlanStep | None
    plan_revision: int  # 0 or 1 — bounded by FR-007
    plan_revision_reason: str | None  # set by replan node (T-056); None on initial plan
    superseded_plan: list[PlanStep]  # pre-revision plan retained by replan (T-056) for activity record (data-model §3)
    plan_event_data: dict[str, Any]  # SSE payload emitted by planner/replan; read by T-058
    replan_event_data: dict[str, Any]  # SSE replan payload {reason, superseded_revision}; set by replan (T-056)
    step_event_data: list[dict[str, Any]]  # SSE events for the current step (started/finished/failed); read by T-058
    clarification_options: list[dict[str, Any]]  # set by planner on needs_clarification path
    budget: _AgentBudget  # read-only snapshot; guard (T-057) reads, no node writes
    _verify_route: str | None  # pre-computed by verify_step to avoid retry_count timing ambiguity
