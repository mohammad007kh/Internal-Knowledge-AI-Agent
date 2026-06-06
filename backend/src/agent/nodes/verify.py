"""verify_step — LangGraph verifier node (T-054).

Grades the retrieval output of the most recent executed step using a
lightweight LLM-based grader.  Implements the R4b routing table via
route_after_verify.

Security: all LLM-generated strings (verdict, reason) are sanitized with
_safe_log before being written to the log.  Langfuse span pattern matches
executor.py (span=None before try, span.end() in finally).
Immutability: past_steps is never mutated in-place — a new list is returned.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState, PlanStep, _Verification
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "retrieval_grader"
_MAX_CHUNK_CHARS = 4_000    # cap per chunk text when building grader input
_MAX_CONTEXT_CHARS = 8_000  # total cap on all concatenated chunk text

_LOG_UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")

_VALID_VERDICTS: frozenset[str] = frozenset({"acceptable", "partial", "unacceptable"})
_RETRY_PREFIX = "[Retry context: "


def _safe_log(value: str, max_len: int = 200) -> str:
    """Strip control + BiDi override characters from LLM-generated strings before logging."""
    cleaned = _LOG_UNSAFE.sub("?", str(value))
    return unicodedata.normalize("NFC", cleaned)[:max_len]


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _build_context(output_chunks: list[dict[str, Any]]) -> str:
    """Concatenate chunk texts, capped per chunk and overall."""
    parts: list[str] = []
    total = 0
    for chunk in output_chunks:
        text = chunk.get("text", "")[:_MAX_CHUNK_CHARS]
        if total + len(text) > _MAX_CONTEXT_CHARS:
            remaining = _MAX_CONTEXT_CHARS - total
            if remaining > 0:
                parts.append(text[:remaining])
            break
        parts.append(text)
        total += len(text)
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------


async def verify_step(
    state: AgentState,
    *,
    langfuse: Langfuse,
    ai_model_resolver: AIModelResolver,
) -> dict[str, Any]:
    """Grade the most recent step result and update verification in past_steps.

    State reads:  current_step, past_steps, trace_id
    State writes: past_steps (full updated list), total_input_tokens,
                  total_output_tokens, current_step (only when retry is triggered)
    """
    current_step: PlanStep | None = state.get("current_step")
    if current_step is None:
        return {"total_input_tokens": 0, "total_output_tokens": 0}

    past_steps: list[dict] = list(state.get("past_steps") or [])

    # Find the most recent StepResult matching current_step["id"]
    step_id = current_step["id"]
    step_result: dict | None = None
    match_idx: int = -1
    for i in range(len(past_steps) - 1, -1, -1):
        if past_steps[i].get("step_id") == step_id:
            step_result = past_steps[i]
            match_idx = i
            break

    if step_result is None:
        logger.warning(
            "verify_step: no StepResult found for step=%s in past_steps",
            _safe_log(step_id),
        )
        return {"total_input_tokens": 0, "total_output_tokens": 0}

    # Use sub_query from current_step (resolved query not stored in StepResult)
    sub_query: str = current_step.get("sub_query", "")
    retrieved_text: str = _build_context(step_result.get("output_chunks") or [])

    span = None
    try:
        span = langfuse.span(
            trace_id=state.get("trace_id", ""),
            name="retrieval_grader",
            input={"step_id": step_id, "sub_query_len": len(sub_query)},
        )

        client = await ai_model_resolver.resolve(_STAGE)
        prompt_template = load_prompt(_STAGE, custom=client.custom_prompt)
        system_prompt = (
            prompt_template
            .replace("{SUB_QUERY}", sub_query)
            .replace("{RETRIEVED_TEXT}", retrieved_text)
        )

        response = await client.http_client.chat.completions.create(
            model=client.model_id,
            messages=[{"role": "system", "content": system_prompt}],
            temperature=client.temperature,
            max_tokens=client.max_tokens,
        )

        raw = response.choices[0].message.content or "{}" if response.choices else "{}"
        # Strip markdown code fences that some models add despite instruction
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("verify_step: step=%s — grader returned non-JSON", _safe_log(step_id))
            parsed = {}

        verdict: str = parsed.get("verdict", "unacceptable")
        reason: str = str(parsed.get("reason", ""))
        checks: dict = parsed.get("checks") or {}

        if verdict not in _VALID_VERDICTS:
            logger.warning(
                "verify_step: step=%s — invalid verdict=%s",
                _safe_log(step_id),
                _safe_log(verdict),
            )
            verdict = "unacceptable"
            reason = "Grader returned invalid verdict"

        logger.info(
            "verify_step: step=%s verdict=%s reason=%s",
            _safe_log(step_id),
            _safe_log(verdict),
            _safe_log(reason),
        )

        # Build updated step result with verification written (immutable)
        updated_result: dict = {
            **step_result,
            "verification": _Verification(
                verdict=verdict,  # type: ignore[arg-type]
                reason=reason,
                checks=checks,
            ),
        }
        updated_past_steps: list[dict] = [
            updated_result if i == match_idx else s
            for i, s in enumerate(past_steps)
        ]

        usage = response.usage
        in_tok: int = usage.prompt_tokens if usage is not None else 0
        out_tok: int = usage.completion_tokens if usage is not None else 0

        delta: dict[str, Any] = {
            "past_steps": updated_past_steps,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

        # Compute routing decision BEFORE any retry_count increment so route_after_verify
        # sees the original value (R4b table evaluated on pre-increment state).
        _plan: list = list(state.get("plan") or [])
        _plan_revision: int = int(state.get("plan_revision") or 0)
        _original_retry: int = int(current_step.get("retry_count", 0))
        _has_remaining: bool = len(_plan) > 0

        if verdict in ("acceptable", "partial"):
            _route = "execute_step" if _has_remaining else "synthesize"
        elif _original_retry < 1:
            _route = "execute_step"
        elif _plan_revision < 1:
            _route = "replan"
        else:
            _route = "synthesize_honest_failure"
        delta["_verify_route"] = _route

        # R4b retry: unacceptable + retry_count < 1 → increment, inject reason into sub_query
        if verdict == "unacceptable" and _original_retry < 1:
            updated_step: dict = {
                **current_step,
                "retry_count": _original_retry + 1,
                "sub_query": f"{_RETRY_PREFIX}{_safe_log(reason)}]\n{current_step.get('sub_query', '')}",
            }
            delta["current_step"] = updated_step

        return delta

    finally:
        if span is not None:
            span.end()


# ---------------------------------------------------------------------------
# Synchronous router
# ---------------------------------------------------------------------------


def route_after_verify(state: AgentState) -> str:
    """R4b routing table — synchronous, reads state only.

    Returns the name of the next node to execute.

    The route is pre-computed by verify_step (stored as _verify_route) so the
    routing decision is always based on the state BEFORE any retry_count increment.
    """
    # verify_step stores the pre-computed route to avoid retry_count timing ambiguity.
    cached: str | None = state.get("_verify_route")  # type: ignore[attr-defined]
    if cached:
        return cached

    # Fallback: compute from current state (safety net when called without verify_step).
    current_step: PlanStep | None = state.get("current_step")
    past_steps: list[dict] = list(state.get("past_steps") or [])
    plan: list[PlanStep] = list(state.get("plan") or [])
    plan_revision: int = int(state.get("plan_revision") or 0)

    if current_step is None:
        return "synthesize"

    step_id = current_step["id"]

    step_result: dict | None = None
    for entry in reversed(past_steps):
        if entry.get("step_id") == step_id:
            step_result = entry
            break

    if step_result is None:
        return "synthesize"

    verdict: str = (step_result.get("verification") or {}).get("verdict", "unacceptable")
    retry_count: int = int(current_step.get("retry_count", 0))
    has_remaining = len(plan) > 0

    if verdict in ("acceptable", "partial"):
        return "execute_step" if has_remaining else "synthesize"

    if retry_count < 1:
        return "execute_step"
    if plan_revision < 1:
        return "replan"
    return "synthesize_honest_failure"
