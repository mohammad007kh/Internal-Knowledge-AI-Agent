"""replan_step — LangGraph replan node (T-056).

Performs the single allowed whole-plan revision (FR-007: ``plan_revision`` 0→1).
The verifier (T-054/T-055) routes here on ``unacceptable & retry_count==1 &
plan_revision<1``; the carried failure ``reason`` informs the revision.

On a valid revision the node:
  1. Guards on ``plan_revision < 1`` (second replan impossible — defence in depth;
     routing is owned by T-054's R4b edge).
  2. Sets ``plan_revision = 1`` and stashes the current plan as ``superseded_plan``
     (retained for the activity record — FR-008).
  3. Calls the revision LLM on the ``planner`` stage slot, reusing the planner's
     ≤5-step cap, structured-output parsing, and source-block rendering.
  4. Runs the SAME server-side permission assertion as the planner
     (``steps[].source_id ⊆ permitted_set``) BEFORE emitting any plan event
     (Security Rule 2). A violation drops to honest-failure — no plan/replan event.
  5. Emits a ``replan`` event ``{reason, superseded_revision: 0}`` THEN a fresh
     ``plan`` event ``{revision: 1, reason, steps}``; the ``reason`` is identical
     across both and equals the carried verifier reason.

Constitution II: the LLM call is Langfuse-traced under the ``planner`` stage and
returns the T-050 token delta. Immutability: the existing plan/state is never
mutated in place — a delta dict is returned.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.agent.nodes.planner import (
    _RESPONSE_FORMAT,
    _build_plan_steps,
    _render_sources_block,
)
from src.agent.state import AgentState, PlanStep
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "planner"  # reuses the planner stage slot — NOT a new slot
_MAX_SUPERSEDED_CHARS = 2_000  # cap on the rendered superseded plan in the prompt

_HONEST_FAILURE_MSG = "Replanning failed: one or more revised sources are not accessible."

# Mirror verify.py's _safe_log: strip control + BiDi override chars from
# LLM-derived strings before logging.
_LOG_UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")


def _safe_log(value: str, max_len: int = 200) -> str:
    """Strip control + BiDi override characters from LLM-derived strings before logging."""
    cleaned = _LOG_UNSAFE.sub("?", str(value))
    return unicodedata.normalize("NFC", cleaned)[:max_len]


def _carried_reason(state: AgentState) -> str:
    """Resolve the verifier's failure reason to carry into the revision + events.

    Preference order:
      1. The most recent matching past_step's verification reason for current_step.
      2. ``plan_revision_reason`` already on state (fallback).
    """
    current_step: PlanStep | None = state.get("current_step")
    past_steps: list[dict[str, Any]] = list(state.get("past_steps") or [])
    if current_step is not None:
        step_id = current_step.get("id")
        for entry in reversed(past_steps):
            if entry.get("step_id") == step_id:
                reason = (entry.get("verification") or {}).get("reason")
                if reason:
                    return str(reason)
                break
    return str(state.get("plan_revision_reason") or "")


def _render_superseded_plan(plan: list[Any]) -> str:
    """Render the superseded plan as compact JSON data for the prompt (capped)."""
    compact = [
        {
            "id": s.get("id", ""),
            "label": s.get("description", ""),
            "source_id": s.get("source_id", ""),
            "sub_query": s.get("sub_query", ""),
            "depends_on": list(s.get("depends_on") or []),
        }
        for s in plan
        if isinstance(s, dict)
    ]
    return json.dumps(compact, ensure_ascii=False)[:_MAX_SUPERSEDED_CHARS]


async def replan_step(
    state: AgentState,
    *,
    langfuse: Langfuse,
    ai_model_resolver: AIModelResolver,
    source_meta_loader: Callable[[list[str]], Awaitable[list[dict[str, Any]]]],
) -> dict[str, Any]:
    """Revise the whole plan once, carrying the verifier reason.

    *source_meta_loader* mirrors the planner's contract: an async callable
    ``(source_ids) -> list[dict]`` where each dict has ``id``/``name``/``purpose``/
    ``examples``/``out_of_scope``.
    """
    plan_revision: int = int(state.get("plan_revision") or 0)

    # Guard (FR-007): the single revision is already spent — second replan impossible.
    # Routing is owned by T-054's R4b edge; this is defence in depth.
    if plan_revision >= 1:
        logger.warning("replan_step: plan_revision>=1 — second revision is impossible; no-op")
        return {"total_input_tokens": 0, "total_output_tokens": 0}

    raw_intent: str = str(state.get("raw_user_intent", state.get("query", ""))).strip()
    permitted_ids: list[str] = list(state.get("source_ids") or [])
    reason: str = _carried_reason(state)
    # Immutability: copy the current plan to retain as the superseded plan.
    superseded_plan: list[Any] = list(state.get("plan") or [])

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name="replan_step",
        input={"reason_len": len(reason), "n_sources": len(permitted_ids)},
    )

    in_tok = out_tok = 0
    try:
        sources = await source_meta_loader(permitted_ids)
        permitted_set = {s["id"] for s in sources}

        client = await ai_model_resolver.resolve(_STAGE)
        prompt_template = load_prompt(_STAGE, custom=client.custom_prompt)
        sources_block = _render_sources_block(sources)
        system_prompt = (
            prompt_template
            .replace("{SOURCES_BLOCK}", sources_block)
            .replace("{FAILURE_REASON}", reason)
            .replace("{SUPERSEDED_PLAN}", _render_superseded_plan(superseded_plan))
        )

        response = await client.http_client.chat.completions.create(
            model=client.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_intent},
            ],
            temperature=client.temperature,
            max_tokens=client.max_tokens,
            response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
        )
        raw = response.choices[0].message.content or "{}"
        in_tok = int(response.usage.prompt_tokens) if response.usage else 0
        out_tok = int(response.usage.completion_tokens) if response.usage else 0

        payload: dict[str, Any] = json.loads(raw)
        raw_steps: list[dict[str, Any]] = list(payload.get("steps") or [])
        plan_steps = _build_plan_steps(raw_steps)  # reuses planner cap (≤5) + parsing

        # Base delta — always retains the revision cap + superseded plan + tokens,
        # even on the honest-failure paths below (immutability: new objects only).
        base_delta: dict[str, Any] = {
            "plan_revision": 1,
            "superseded_plan": superseded_plan,
            "plan_revision_reason": reason,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

        # Guard: zero-step or empty-source_id plans are semantically invalid.
        if not plan_steps or any(not s["source_id"] for s in plan_steps):
            logger.warning("replan_step: empty or malformed revised plan — honest-failure")
            span.update(output={"decision": "malformed_plan"})
            return {**base_delta, "error": _HONEST_FAILURE_MSG}

        # Security Rule 2: assert source_id ⊆ permitted_set BEFORE any plan event.
        violating = [s for s in plan_steps if s["source_id"] not in permitted_set]
        if violating:
            logger.warning(
                "replan_step: permission assertion FAILED — %d violating source_ids; honest-failure",
                len(violating),
            )
            span.update(output={"decision": "permission_violation", "n_violating": len(violating)})
            return {**base_delta, "error": _HONEST_FAILURE_MSG}

        # Build the SSE event payloads: replan THEN plan(revision:1). The reason is
        # identical across both and equals the carried verifier reason.
        source_name_map = {s["id"]: s.get("name", "") for s in sources}
        replan_event_data: dict[str, Any] = {
            "reason": reason,
            "superseded_revision": 0,
        }
        plan_event_data: dict[str, Any] = {
            "revision": 1,
            "reason": reason,
            "steps": [
                {
                    "id": step["id"],
                    "label": step["description"],
                    "source_id": step["source_id"],
                    "source_name": source_name_map.get(step["source_id"], ""),
                    "depends_on": step["depends_on"],
                }
                for step in plan_steps
            ],
        }

        span.update(output={"decision": "replan", "n_steps": len(plan_steps), "revision": 1})
        logger.info(
            "replan_step: revised plan n_steps=%d reason=%s",
            len(plan_steps),
            _safe_log(reason),
        )
        return {
            **base_delta,
            "plan": plan_steps,
            "replan_event_data": replan_event_data,
            "plan_event_data": plan_event_data,
        }

    except Exception:
        logger.error("replan_step: LLM call failed", exc_info=True)
        span.update(output={"decision": "error"})
        return {
            "plan_revision": 1,
            "superseded_plan": superseded_plan,
            "plan_revision_reason": reason,
            "error": _HONEST_FAILURE_MSG,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }
    finally:
        span.end()
