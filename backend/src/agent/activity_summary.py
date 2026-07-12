"""Compact activity-summary builder (T-058 / FR-018, FR-021).

Pure, dependency-free helper that distils a finished agentic turn's
``AgentState`` into the *compact* shape persisted on
``chat_messages.activity_summary`` and emitted on the ``done`` SSE event
(data-model §3).

Only application-generated narration is carried here — never a raw row slice
(security rule 5). ``roles[].line`` and plan ``label`` strings are capped at
:data:`_MAX_LINE_CHARS` (200) and run through control/BiDi sanitisation so
nothing crafted in a source name / LLM string can escape into the persisted
JSONB or the SSE wire frame.

The whole module is pure: it reads the final state dict and returns a plain
``dict`` (JSON-serialisable). The v2 / legacy paths never populate the agentic
plan fields, so :func:`build_activity_summary` returns ``None`` for them and the
``done`` event simply omits the summary (the UI hides what is absent).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Cap on every persisted/emitted free-text line (security rule 5; mirrors the
# 200-char caps already enforced in the executor/verify/budget_guard nodes and
# the migration 0037 note).
_MAX_LINE_CHARS = 200

# Mirror the node-level sanitisers (_safe_log / _safe_text): strip control +
# BiDi override characters from any data-/LLM-derived string before it lands in
# the JSONB column or the SSE frame.
_LOG_UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")

# Budget-fraction thresholds for the human cost label (data-model §3).
_COST_SMALL_MAX = 0.34   # < 34 % of the token ceiling → "small"
_COST_MEDIUM_MAX = 0.67  # < 67 % → "medium"; otherwise "large"


def _safe_line(value: object, max_len: int = _MAX_LINE_CHARS) -> str:
    """Sanitise + cap a data-derived string (security rule 5)."""
    cleaned = _LOG_UNSAFE.sub(" ", str(value))
    return unicodedata.normalize("NFC", cleaned).strip()[:max_len]


def _cost_label(turn_tokens: dict[str, int], budget: dict[str, Any]) -> str:
    """Derive small|medium|large from spend as a fraction of the token ceiling.

    Falls back to ``"small"`` when no positive ceiling is configured so the
    label is always one of the three documented values.
    """
    ceiling = budget.get("token_ceiling")
    if not isinstance(ceiling, int) or ceiling <= 0:
        return "small"
    spend = int(turn_tokens.get("input", 0)) + int(turn_tokens.get("output", 0))
    fraction = spend / ceiling
    if fraction < _COST_SMALL_MAX:
        return "small"
    if fraction < _COST_MEDIUM_MAX:
        return "medium"
    return "large"


def _plan_entry(step: dict[str, Any]) -> dict[str, Any]:
    """Project a PlanStep into the compact ``{id, label, status}`` plan row."""
    return {
        "id": _safe_line(step.get("id", ""), 80),
        "label": _safe_line(step.get("description") or step.get("sub_query") or "", _MAX_LINE_CHARS),
        "status": _safe_line(step.get("status", "pending"), 20),
    }


def _completed_plan(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the executed plan from ``past_steps`` + remaining ``plan``.

    ``past_steps`` holds executed StepResults (one entry per execution, so a
    retried step appears twice); ``plan`` holds the steps not yet dispatched.
    For the compact summary we want one row per *distinct* step in plan order:
    a step is ``done`` when its last verification verdict is acceptable/partial,
    ``failed`` on unacceptable, else its current ``plan`` status.
    """
    # Verdict by step_id from the LAST matching past_step (retries overwrite).
    verdict_by_id: dict[str, str] = {}
    for entry in state.get("past_steps") or []:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("step_id")
        verdict = (entry.get("verification") or {}).get("verdict")
        if sid is not None and verdict:
            verdict_by_id[str(sid)] = str(verdict)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Executed steps first, in execution order.
    for entry in state.get("past_steps") or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("step_id", ""))
        if not sid or sid in seen:
            continue
        seen.add(sid)
        verdict = verdict_by_id.get(sid, "")
        if verdict in ("acceptable", "partial"):
            status = "done"
        elif verdict == "unacceptable":
            status = "failed"
        else:
            status = "active"
        # Resolve a human label from plan / current_step / superseded.
        label = _label_for_step(state, sid)
        rows.append({"id": _safe_line(sid, 80), "label": label, "status": status})

    # Then any still-pending plan steps not yet executed.
    for step in state.get("plan") or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id", ""))
        if sid in seen:
            continue
        seen.add(sid)
        rows.append(_plan_entry(step))

    return rows


def _label_for_step(state: dict[str, Any], step_id: str) -> str:
    """Resolve a step's human label across plan / current_step / superseded."""
    candidates: list[Any] = []
    candidates.extend(state.get("plan") or [])
    current = state.get("current_step")
    if isinstance(current, dict):
        candidates.append(current)
    candidates.extend(state.get("superseded_plan") or [])
    for step in candidates:
        if isinstance(step, dict) and str(step.get("id", "")) == step_id:
            return _safe_line(step.get("description") or step.get("sub_query") or step_id)
    return _safe_line(step_id, 80)


def _source_count(state: dict[str, Any]) -> int:
    """Count DISTINCT sources actually queried across the executed plan."""
    seen: set[str] = set()
    for step in state.get("plan") or []:
        if isinstance(step, dict) and step.get("source_id"):
            seen.add(str(step["source_id"]))
    current = state.get("current_step")
    if isinstance(current, dict) and current.get("source_id"):
        seen.add(str(current["source_id"]))
    for step in state.get("superseded_plan") or []:
        if isinstance(step, dict) and step.get("source_id"):
            seen.add(str(step["source_id"]))
    return len(seen)


def _roles(state: dict[str, Any], *, had_replan: bool, budget_hit: bool) -> list[dict[str, Any]]:
    """Build the per-role one-liner accordion (review mode), capped at 200 chars."""
    roles: list[dict[str, Any]] = []

    plan = state.get("plan") or []
    current = state.get("current_step")
    planner_steps = list(plan)
    if isinstance(current, dict):
        planner_steps = [current, *planner_steps]
    if planner_steps or state.get("past_steps"):
        labels = [
            _safe_line(s.get("description") or s.get("sub_query") or s.get("id") or "", 60)
            for s in planner_steps
            if isinstance(s, dict)
        ]
        line = ", ".join(label for label in labels if label) or "planned the turn"
        roles.append({"role": "planner", "line": _safe_line(line)})

    if had_replan:
        roles.append(
            {
                "role": "planner",
                "line": _safe_line(
                    "revised the plan: " + (state.get("plan_revision_reason") or "")
                ),
            }
        )

    for entry in state.get("past_steps") or []:
        if not isinstance(entry, dict):
            continue
        sid = _safe_line(entry.get("step_id", ""), 80)
        narration = entry.get("narration") or ""
        roles.append(
            {"role": "executor", "step": sid, "line": _safe_line(narration)}
        )
        verification = entry.get("verification") or {}
        verdict = verification.get("verdict")
        if verdict:
            reason = verification.get("reason") or ""
            roles.append(
                {
                    "role": "verifier",
                    "step": sid,
                    "line": _safe_line(f"{verdict}: {reason}".strip(": ")),
                }
            )

    if budget_hit:
        roles.append(
            {"role": "budget", "line": _safe_line("turn stopped at a cost/time ceiling")}
        )

    return roles


def build_activity_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    """Distil a finished agentic turn into the compact summary (data-model §3).

    Returns ``None`` for non-agentic turns (v2 / legacy) — detected by the
    absence of BOTH a plan and any executed steps — so the ``done`` event and
    the persisted column stay null and the UI degrades gracefully.
    """
    past_steps = state.get("past_steps") or []
    plan = state.get("plan") or []
    superseded = state.get("superseded_plan") or []

    # Non-agentic turn → no summary.
    if not past_steps and not plan and not superseded:
        return None

    budget = state.get("budget") or {}
    turn_tokens = {
        "input": int(state.get("total_input_tokens") or 0),
        "output": int(state.get("total_output_tokens") or 0),
    }

    plan_revision = int(state.get("plan_revision") or 0)
    had_replan = plan_revision > 0 or bool(superseded)
    budget_hit = bool(state.get("budget_hit"))

    # had_failure: any retry (a step executed more than once) OR any
    # unacceptable verdict OR a budget abstain.
    seen_ids: set[str] = set()
    had_retry = False
    had_unacceptable = False
    for entry in past_steps:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("step_id", ""))
        if sid in seen_ids:
            had_retry = True
        seen_ids.add(sid)
        if (entry.get("verification") or {}).get("verdict") == "unacceptable":
            had_unacceptable = True
    had_failure = had_retry or had_unacceptable or budget_hit

    completed_plan = _completed_plan(state)

    superseded_plan: list[dict[str, Any]] | None = None
    if had_replan and superseded:
        superseded_plan = [
            _plan_entry(s) for s in superseded if isinstance(s, dict)
        ]

    revision_reason = (
        _safe_line(state.get("plan_revision_reason") or "") or None
        if had_replan
        else None
    )

    return {
        "step_count": len(completed_plan),
        "source_count": _source_count(state),
        "had_replan": had_replan,
        "had_failure": had_failure,
        "budget_hit": budget_hit,
        "turn_tokens": turn_tokens,
        "cost_label": _cost_label(turn_tokens, budget),
        "plan": completed_plan,
        "superseded_plan": superseded_plan,
        "revision_reason": revision_reason,
        "roles": _roles(state, had_replan=had_replan, budget_hit=budget_hit),
    }
