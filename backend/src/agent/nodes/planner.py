"""plan_query — LangGraph planner node (T-052).

Decomposes ``raw_user_intent`` into a bounded (≤ 5 steps), permission-clipped
execution plan using the ``planner`` LLM slot, or routes to a clarify-with-options
request when genuinely ambiguous.

Security Rule 2 (plan.md): ``steps[].source_id ⊆ permitted_set`` is asserted
server-side BEFORE the plan event payload is returned.  Any LLM-hallucinated
out-of-set source_id drops to the honest-failure path — no plan emitted, no
source names leaked.
"""
from __future__ import annotations

import html
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState, PlanStep
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "planner"
_MAX_STEPS = 5  # FR-007 hard cap — enforced in code, not just in the prompt

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "planner_decision",
        "strict": False,
        "schema": {
            "type": "object",
            "required": ["decision"],
            "properties": {
                "decision": {"type": "string", "enum": ["plan", "needs_clarification"]},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "label", "source_id", "sub_query", "depends_on"],
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "source_id": {"type": "string"},
                            "sub_query": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "question": {"type": ["string", "null"]},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["label", "source_id"],
                        "properties": {
                            "label": {"type": "string"},
                            "source_id": {"type": "string"},
                        },
                    },
                },
                "allow_free_text": {"type": ["boolean", "null"]},
            },
        },
    },
}


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _render_sources_block(sources: list[dict[str, Any]]) -> str:
    """Render permitted-source metadata as delimited data (Security Rule 1 — never instructions).

    All field values are HTML-escaped (quote=True) to prevent XML attribute injection
    and element-escape vectors from crafted source names/metadata.
    """
    parts: list[str] = []
    for s in sources:
        sid = _escape(s.get("id", ""))
        name = _escape(s.get("name", ""))
        purpose = _escape(s.get("purpose") or "")
        examples = _escape(s.get("examples") or "")
        out_of_scope = _escape(s.get("out_of_scope") or "")
        parts.append(
            f'<source id="{sid}" name="{name}">\n'
            f"<source_purpose>{purpose}</source_purpose>\n"
            f"<source_examples>{examples}</source_examples>\n"
            f"<source_out_of_scope>{out_of_scope}</source_out_of_scope>\n"
            f"</source>"
        )
    return "\n".join(parts)


def _build_plan_steps(raw_steps: list[dict[str, Any]]) -> list[PlanStep]:
    """Convert LLM step dicts to PlanStep TypedDicts, capped at _MAX_STEPS."""
    return [
        PlanStep(
            id=s.get("id", f"s{i + 1}"),
            description=s.get("label", ""),
            source_id=s.get("source_id", ""),
            sub_query=s.get("sub_query", ""),
            depends_on=list(s.get("depends_on") or []),
            status="pending",
            retry_count=0,
        )
        for i, s in enumerate(raw_steps[:_MAX_STEPS])
    ]


async def plan_query(
    state: AgentState,
    *,
    langfuse: Langfuse,
    ai_model_resolver: AIModelResolver,
    source_meta_loader: Callable[[list[str]], Awaitable[list[dict[str, Any]]]],
) -> dict[str, Any]:
    """Decompose ``raw_user_intent`` into a bounded plan or a clarification request.

    *source_meta_loader* is an async callable ``(source_ids) -> list[dict]`` where each
    dict has keys: ``id``, ``name``, ``purpose``, ``examples``, ``out_of_scope``.
    The pipeline builder (T-058) partially applies a real DB loader; unit tests pass a
    simple coroutine over fixture data.
    """
    raw_intent: str = state.get("raw_user_intent", state.get("query", "")).strip()
    permitted_ids: list[str] = list(state.get("source_ids") or [])
    plan_revision: int = int(state.get("plan_revision") or 0)

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name="plan_query",
        input={"query": raw_intent, "n_sources": len(permitted_ids)},
    )

    in_tok = out_tok = 0
    try:
        sources = await source_meta_loader(permitted_ids)
        permitted_set = {s["id"] for s in sources}

        client = await ai_model_resolver.resolve(_STAGE)
        prompt_template = load_prompt(_STAGE, custom=client.custom_prompt)
        sources_block = _render_sources_block(sources)
        system_prompt = prompt_template.replace("{SOURCES_BLOCK}", sources_block)

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
        decision = payload.get("decision", "plan")

        # ── Clarification path ──────────────────────────────────────────────
        if decision == "needs_clarification":
            question: str = (
                payload.get("question")
                or "Could you clarify which data source you'd like to query?"
            )
            raw_options: list[dict[str, Any]] = list(payload.get("options") or [])
            # Security Rule 2 — clarification path (BOTH clauses, FX41 parity):
            #   1. an option's ``source_id`` must be ∈ permitted_set; and
            #   2. an option may never NAME an inaccessible source.
            # The LLM-authored ``label`` is FREE TEXT and could name any source
            # (incl. one outside the permitted set), so we DROP it and re-key the
            # human-readable name to the TRUSTED, server-loaded display name of
            # the SAME permitted ``source_id`` — the very ``source_name_map`` the
            # plan path uses below.  The emitter (chat_stream_service) then has a
            # trusted ``source_name`` keyed by the (re-clipped) ``source_id`` and
            # never has to trust the LLM's free-text label/hint.
            clarify_name_map = {s["id"]: s.get("name", "") for s in sources}
            safe_options = [
                {
                    "source_id": opt["source_id"],
                    "source_name": clarify_name_map.get(opt["source_id"], ""),
                }
                for opt in raw_options
                if opt.get("source_id") in permitted_set
            ][:4]
            span.update(
                output={"decision": "needs_clarification", "n_options": len(safe_options)}
            )
            logger.info("plan_query: needs_clarification n_options=%d", len(safe_options))
            return {
                "requires_clarification": True,
                "clarification_question": question,
                "clarification_options": safe_options,
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # ── Plan path ───────────────────────────────────────────────────────
        raw_steps: list[dict[str, Any]] = list(payload.get("steps") or [])
        plan_steps = _build_plan_steps(raw_steps)

        # Guard: zero-step plan is semantically invalid.
        if not plan_steps:
            logger.warning("plan_query: LLM returned decision='plan' with zero steps — rejecting")
            span.update(output={"decision": "empty_plan"})
            return {
                "error": "Planner failed to generate a plan.",
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # Guard: malformed steps with empty source_id (strict=False allows LLM to omit the field).
        malformed = [s for s in plan_steps if not s["source_id"]]
        if malformed:
            logger.warning("plan_query: %d step(s) have empty source_id — rejecting plan", len(malformed))
            span.update(output={"decision": "malformed_plan", "n_malformed": len(malformed)})
            return {
                "error": "Planner failed to generate a plan.",
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # Security Rule 2: assert source_id ⊆ permitted_set BEFORE emitting any plan event.
        violating = [s for s in plan_steps if s["source_id"] not in permitted_set]
        if violating:
            logger.warning(
                "plan_query: permission assertion FAILED — %d violating source_ids; honest-failure",
                len(violating),
            )
            span.update(
                output={"decision": "permission_violation", "n_violating": len(violating)}
            )
            return {
                "error": "Planning failed: one or more planned sources are not accessible.",
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # Build SSE plan event payload (matches contracts/sse-events.md).
        source_name_map = {s["id"]: s.get("name", "") for s in sources}
        plan_event_data: dict[str, Any] = {
            "revision": plan_revision,
            "reason": state.get("plan_revision_reason") if plan_revision > 0 else None,
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

        span.update(
            output={"decision": "plan", "n_steps": len(plan_steps), "revision": plan_revision}
        )
        logger.info(
            "plan_query: plan n_steps=%d revision=%d", len(plan_steps), plan_revision
        )
        return {
            "plan": plan_steps,
            "plan_event_data": plan_event_data,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    except Exception:
        logger.error("plan_query: LLM call failed", exc_info=True)
        span.update(output={"decision": "error"})
        return {
            "error": "Planner failed to generate a plan.",
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }
    finally:
        span.end()
