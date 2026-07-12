"""Deterministic budget guard + diagnostics injector (T-057).

This module is the HARD-BOUNDS layer of the plan-and-execute agent (FR-019 /
FR-020 / FR-013).  It contains NO LLM call and NO graph dependency — every
function here is pure and unit-testable in isolation:

* :func:`budget_guard` — a deterministic edge check.  Given the current
  ``AgentState`` and an injected ``now`` it compares accumulated spend against
  the read-only ``budget`` snapshot and returns a :class:`BudgetDecision`.  When
  ANY cap is breached the decision routes to the synthesizer with
  ``budget_hit=True`` and carries the ``budget`` SSE event payload (contract
  shape: ``{ceiling_hit, not_completed, offer_continue}``).  The graph builder
  (T-058) wires this as a conditional edge BEFORE each step dispatch and BEFORE
  replan; this module never touches LangGraph.

* :func:`inject_diagnostics` — builds a ``<RETRIEVAL_DIAGNOSTICS>`` block from
  ``past_steps`` (sources queried, generated SQL, ROW COUNTS, verification
  reasons) as GENERATED narration in the "first-3 + count" style.  It NEVER
  emits raw row slices beyond the first three and ALWAYS runs every
  data-/LLM-derived string through redaction + control-char sanitisation
  (security rule 5; mirrors ``verify.py``'s ``_safe_log`` and reuses
  ``redact_dsn`` from ``db_safety``).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.agent.state import AgentState
from src.services.db_safety import redact_dsn

# The route string the guard returns on a breach.  The T-058 graph maps this to
# the synthesizer node (same node that serves the honest-failure branch).
SYNTHESIZER_ROUTE = "synthesize"

# Number of result rows narrated verbatim before collapsing to a "(+N more)"
# count — the "first-3 + count" rule (security rule 5).
_NARRATE_ROWS = 3

# Mirror verify.py's _safe_log: strip control + BiDi override chars from any
# data-/LLM-derived string before it lands in the prompt or a log line.
_LOG_UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")

_MAX_REASON_CHARS = 200
_MAX_SQL_CHARS = 500


def _safe_text(value: object, max_len: int = _MAX_REASON_CHARS) -> str:
    """Strip control + BiDi override chars from a data-derived string (security rule 5).

    Mirrors ``verify.py._safe_log``; also runs ``redact_dsn`` first so any
    connection string embedded in SQL or a reason can never escape into the
    synthesizer prompt.
    """
    redacted = redact_dsn(value)  # str()-coerces internally
    cleaned = _LOG_UNSAFE.sub(" ", redacted)
    return unicodedata.normalize("NFC", cleaned).strip()[:max_len]


@dataclass(frozen=True)
class BudgetDecision:
    """Immutable result of a guard evaluation (pure-function output).

    ``budget_hit`` — True when any cap was breached.
    ``route`` — the next-node route string on a breach, else ``None``.
    ``event`` — the ``budget`` SSE payload on a breach, else ``None``.
    ``not_completed`` — pending plan-step labels (also embedded in ``event``).
    ``breached_caps`` — names of the caps that tripped (diagnostics/testing).
    ``state_delta`` — the dict patch a node would merge (``budget_hit`` +
        ``budget_event_data``) so the synthesizer/stream layer can read it.
    """

    budget_hit: bool
    route: str | None
    event: dict[str, Any] | None
    not_completed: tuple[str, ...]
    breached_caps: tuple[str, ...]
    state_delta: dict[str, Any]


def _pending_labels(state: AgentState) -> list[str]:
    """Labels/descriptions of PENDING (unexecuted) plan steps.

    The ``plan`` field holds the steps NOT yet dispatched (executed results live
    in ``past_steps`` and the in-flight one in ``current_step``), so every entry
    in ``plan`` is "not completed" at the moment the ceiling trips.
    """
    plan = state.get("plan") or []
    labels: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        label = step.get("description") or step.get("sub_query") or step.get("id") or ""
        labels.append(_safe_text(label))
    return labels


def _parse_deadline(deadline: str | None) -> datetime | None:
    """Parse an ISO-8601 deadline; return ``None`` on absent/malformed input.

    A malformed deadline must NEVER blow up the deterministic guard — it simply
    means "no time cap" (fail-open on the clock; the other caps still bound the
    loop).
    """
    if not deadline or not isinstance(deadline, str):
        return None
    try:
        parsed = datetime.fromisoformat(deadline)
    except (ValueError, TypeError):
        return None
    # Treat a naive deadline as UTC so the comparison is well-defined.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def budget_guard(
    state: AgentState,
    *,
    now: datetime | None = None,
    synthesizer_prompt_tokens: int = 0,
    synthesizer_max_tokens: int = 0,
) -> BudgetDecision:
    """Deterministic hard-bounds check at a loop EDGE — no LLM (FR-019).

    Runs BEFORE each step dispatch and BEFORE replan.  Compares accumulated
    state to the read-only ``budget`` snapshot:

    * steps used (``len(past_steps)``) vs ``max_steps``;
    * current step ``retry_count`` vs ``max_retries_per_step``;
    * ``plan_revision`` vs ``max_revisions``;
    * ``total_input_tokens + total_output_tokens`` PLUS a synthesizer pre-call
      estimate (``synthesizer_prompt_tokens + synthesizer_max_tokens``) vs
      ``token_ceiling`` — the synthesizer's own call is bounded by its
      ``max_tokens``, so estimating it here keeps the final answer affordable
      (R2);
    * wall-clock ``now`` vs the ISO-8601 ``deadline``.

    On ANY breach it returns a :class:`BudgetDecision` with ``budget_hit=True``,
    ``route`` = the synthesizer, and the ``budget`` SSE event
    ``{ceiling_hit: true, not_completed: [...pending step labels...],
    offer_continue: true}``.

    **Edge-only / overshoot-by-one (R2):** this is an EDGE check — it cannot
    interrupt an in-flight step.  Because there is no intra-step check, a single
    step already dispatched may overshoot a cap by at most one step's spend
    (SQL-gen + heavy-judge within that step).  This is deliberate and bounded by
    ``max_steps × worst-case-step-spend + synthesizer max_tokens``.

    **"Keep going" / no mid-turn raise (FR-020):** when the ceiling trips the
    UI may offer a "Keep going" quick-reply.  That reply is an ORDINARY
    next-turn user message that starts a NEW turn with a FRESH budget — the
    per-turn cap is NEVER raised mid-turn.  This is documented here, not
    implemented as a mid-turn raise; this function only ever LOWERS activity by
    routing to the synthesizer.

    Pure function: depends only on its arguments (``now`` is injected so tests
    control the wall-clock without sleeping) and returns an immutable
    :class:`BudgetDecision`.  The graph builder (T-058) owns the wiring.
    """
    now = now or datetime.now(UTC)
    budget = state.get("budget") or {}

    steps_used = len(state.get("past_steps") or [])
    current_step = state.get("current_step") or {}
    retry_count = int(current_step.get("retry_count", 0)) if isinstance(current_step, dict) else 0
    plan_revision = int(state.get("plan_revision") or 0)
    spend = int(state.get("total_input_tokens") or 0) + int(state.get("total_output_tokens") or 0)
    projected_spend = spend + int(synthesizer_prompt_tokens) + int(synthesizer_max_tokens)

    breached: list[str] = []

    max_steps = budget.get("max_steps")
    if isinstance(max_steps, int) and steps_used >= max_steps:
        breached.append("step")

    max_retries = budget.get("max_retries_per_step")
    if isinstance(max_retries, int) and retry_count > max_retries:
        breached.append("retry")

    max_revisions = budget.get("max_revisions")
    if isinstance(max_revisions, int) and plan_revision > max_revisions:
        breached.append("revision")

    token_ceiling = budget.get("token_ceiling")
    if isinstance(token_ceiling, int) and projected_spend > token_ceiling:
        breached.append("token")

    deadline = _parse_deadline(budget.get("deadline"))
    if deadline is not None and now >= deadline:
        breached.append("deadline")

    if not breached:
        return BudgetDecision(
            budget_hit=False,
            route=None,
            event=None,
            not_completed=(),
            breached_caps=(),
            state_delta={"budget_hit": False},
        )

    not_completed = _pending_labels(state)
    event: dict[str, Any] = {
        "ceiling_hit": True,
        "not_completed": not_completed,
        "offer_continue": True,
    }
    return BudgetDecision(
        budget_hit=True,
        route=SYNTHESIZER_ROUTE,
        event=event,
        not_completed=tuple(not_completed),
        breached_caps=tuple(breached),
        state_delta={"budget_hit": True, "budget_event_data": event},
    )


# ---------------------------------------------------------------------------
# Diagnostics injector
# ---------------------------------------------------------------------------


def _narrate_rows(output_chunks: list[Any]) -> str:
    """Narrate a result set as "first-3 + count" — NEVER a raw slice (security rule 5).

    Only the first three chunks' identifier-prefixed values are surfaced (already
    sanitised + DSN-redacted); rows 4+ collapse to a ``(+N more)`` count so no raw
    row data beyond the narrated head ever reaches the prompt.
    """
    count = len(output_chunks)
    if count == 0:
        return "0 rows"
    head: list[str] = []
    for chunk in output_chunks[:_NARRATE_ROWS]:
        text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        head.append(_safe_text(text, 80))
    extra = count - len(head)
    suffix = f" (+{extra} more)" if extra > 0 else ""
    return f"{count} rows: " + "; ".join(p for p in head if p) + suffix


def inject_diagnostics(state: AgentState) -> str:
    """Build the ``<RETRIEVAL_DIAGNOSTICS>`` block from ``past_steps`` (FR-013).

    GENERATED narration only — sources queried, the generated SQL (DSN-redacted),
    ROW COUNTS (first-3 + count), and verification reasons.  Never a raw row slice
    (security rule 5).  Every data-derived string is sanitised via
    :func:`_safe_text` (control/BiDi strip + ``redact_dsn``).  Always returns a
    well-formed block, even when ``past_steps`` is empty, so the synthesizer
    prompt placeholder is never left dangling.
    """
    past_steps = state.get("past_steps") or []
    lines: list[str] = ["<RETRIEVAL_DIAGNOSTICS>"]

    if not past_steps:
        lines.append("No retrieval steps were executed.")
    else:
        for entry in past_steps:
            if not isinstance(entry, dict):
                continue
            step_id = _safe_text(entry.get("step_id", "?"), 40)
            source_id = _safe_text(_source_id_for(state, entry.get("step_id")), 80)
            generated_sql = entry.get("generated_sql")
            verification = entry.get("verification") or {}
            verdict = _safe_text(verification.get("verdict", "unknown"), 40)
            reason = _safe_text(verification.get("reason", ""), _MAX_REASON_CHARS)
            rows = _narrate_rows(entry.get("output_chunks") or [])

            parts = [f"- step {step_id}: source={source_id or 'unknown'}"]
            if generated_sql:
                parts.append(f"sql=[{_safe_text(generated_sql, _MAX_SQL_CHARS)}]")
            parts.append(f"result={rows}")
            parts.append(f"verdict={verdict}")
            if reason:
                parts.append(f"reason={reason}")
            lines.append("; ".join(parts))

    lines.append("</RETRIEVAL_DIAGNOSTICS>")
    return "\n".join(lines)


def _source_id_for(state: AgentState, step_id: object) -> str:
    """Resolve the source_id queried for a given step from the plan/current_step.

    ``StepResult`` does not carry the source_id directly, so we look it up from
    the plan steps / current_step / superseded_plan by id.  Returns ``""`` when
    unresolved.
    """
    if step_id is None:
        return ""
    candidates: list[Any] = []
    candidates.extend(state.get("plan") or [])
    current = state.get("current_step")
    if isinstance(current, dict):
        candidates.append(current)
    candidates.extend(state.get("superseded_plan") or [])
    for step in candidates:
        if isinstance(step, dict) and step.get("id") == step_id:
            return str(step.get("source_id", ""))
    return ""
