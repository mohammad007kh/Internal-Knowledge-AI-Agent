"""query_analyzer — LangGraph node that rewrites the user query into 1-3
search-friendly variants for higher retrieval recall.

Resolver slot: ``query_analyzer``.  On any LLM/parse error the node
degrades to the single-variant fallback ``[query]`` so retrieve always
has at least one search string.

State writes:
* ``query_variants: list[str]``
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "query_analyzer"
_MAX_VARIANTS = 3

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "query_rewrite",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["rewritten", "variants"],
            "properties": {
                "rewritten": {"type": "string"},
                "variants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_VARIANTS,
                    "items": {"type": "string"},
                },
            },
        },
    },
}

_HISTORY_TURNS = 6  # last N turns of conversation passed to the rewriter


def _fallback(query: str) -> list[str]:
    """Single-variant fallback used on any LLM error."""
    return [query] if query else []


def _format_history(messages: list[Any] | None) -> str:
    """Render the last N message turns as plain text for the rewriter prompt.

    Order: oldest first.  Empty string when no history (e.g. first turn).
    """
    if not messages:
        return ""
    # Defensive: messages can be langchain BaseMessage subclasses.  Read
    # role from `.type` (langchain) and content from `.content`.
    rendered: list[str] = []
    for msg in messages[-_HISTORY_TURNS:]:
        role_attr = getattr(msg, "type", None) or getattr(msg, "role", None)
        content = getattr(msg, "content", None)
        if not isinstance(content, str) or not content.strip():
            continue
        role = "User" if role_attr in ("human", "user") else "Assistant"
        rendered.append(f"{role}: {content.strip()}")
    return "\n".join(rendered)


async def _call_llm(
    query: str,
    *,
    history: str,
    ai_model_resolver: AIModelResolver,
    reflector_feedback: str | None = None,
) -> tuple[str, list[str]]:
    """Return ``(rewritten_query, variants)``."""
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    # Build the user message: history + latest query.  When the reflector
    # flagged a retry, append its feedback so the next batch of variants
    # addresses the rejection (Slice E defect-2 fix).
    parts: list[str] = []
    if history:
        parts.append(f"CONVERSATION HISTORY:\n{history}")
    parts.append(f"LATEST USER MESSAGE:\n{query}")
    if reflector_feedback:
        parts.append(
            "Previous attempt was rejected because: "
            f"{reflector_feedback}. "
            "Generate variants that would address this."
        )
    user_content = "\n\n".join(parts)
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    rewritten = payload.get("rewritten") or query
    if not isinstance(rewritten, str) or not rewritten.strip():
        rewritten = query
    rewritten = rewritten.strip()

    variants_raw = payload.get("variants") or []
    variants: list[str] = []
    for v in variants_raw[:_MAX_VARIANTS]:
        if isinstance(v, str) and v.strip():
            variants.append(v.strip())
    if not variants:
        variants = [rewritten]
    # Always ensure rewritten is the first variant.
    if variants[0] != rewritten:
        variants.insert(0, rewritten)
        variants = variants[:_MAX_VARIANTS]
    return rewritten, variants


async def analyze_query(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    langfuse: Langfuse,
) -> dict[str, Any]:
    """Resolve the slot, call the LLM, write ``query_variants``.

    Defensive: any error returns ``[query]`` so retrieve still runs.
    """
    query: str = (state.get("query") or "").strip()
    if not query:
        return {"query_variants": []}

    reflector_feedback: str | None = state.get("reflector_feedback")
    # load_history may include the current turn (it queries the DB AFTER
    # chat.py persisted the user row). Drop trailing turns that match the
    # latest query verbatim — they're already passed as LATEST USER MESSAGE
    # to the rewriter and would corrupt the history block (the rewriter
    # would see "User: <query>" both at the bottom of history AND as the
    # latest message, causing it to refuse to resolve pronouns/follow-ups).
    msgs = state.get("messages") or []
    trimmed = list(msgs)
    while trimmed:
        last = trimmed[-1]
        last_content = getattr(last, "content", None)
        last_type = getattr(last, "type", None) or getattr(last, "role", None)
        if (
            isinstance(last_content, str)
            and last_content.strip() == query
            and last_type in ("human", "user")
        ):
            trimmed.pop()
        else:
            break
    if len(trimmed) != len(msgs):
        logger.debug(
            "query_analyzer: trimmed %d trailing turn(s) matching latest query",
            len(msgs) - len(trimmed),
        )
    history = _format_history(trimmed)

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={
            "query": query,
            "history_turns": len(history.splitlines()) if history else 0,
            "has_reflector_feedback": bool(reflector_feedback),
        },
    )
    degraded = False
    try:
        try:
            rewritten, variants = await _call_llm(
                query,
                history=history,
                ai_model_resolver=ai_model_resolver,
                reflector_feedback=reflector_feedback,
            )
        except Exception as exc:  # noqa: BLE001 - degrade
            # FX5/RC4: don't swallow the failure silently. Mark the
            # request as degraded so downstream retrieve_context can
            # apply its prior-turn concatenation stop-gap, log at
            # WARNING with the exception class+message, and surface a
            # warning marker on the Langfuse span.  We still don't
            # raise — pipeline continuity is more important than
            # one stage failing cleanly.
            degraded = True
            logger.warning(
                "query_analyzer: LLM call failed, falling back to single variant: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            try:
                # Best-effort warning marker on the span; the v2 SDK
                # exposes no level field on .update(), so encode the
                # warning in the output payload that the dashboard renders.
                span.update(
                    output={
                        "level": "WARNING",
                        "degraded": True,
                        "error_class": type(exc).__name__,
                        "error_message": str(exc)[:200],
                    }
                )
            except Exception:  # noqa: BLE001 - never let tracing kill the request
                logger.debug("query_analyzer: span warning emit failed", exc_info=True)
            rewritten = query
            variants = _fallback(query)

        if not degraded:
            span.update(
                output={"rewritten": rewritten[:200], "variant_count": len(variants)}
            )
        logger.info(
            "query_analyzer: rewrote %r -> %r (%d variants)%s",
            query[:80],
            rewritten[:80],
            len(variants),
            " [DEGRADED]" if degraded else "",
        )
        # Write the history-resolved rewrite back to state["query"] so
        # downstream nodes (retrieve_context, source_router) see the
        # self-contained version. The original user message is preserved
        # verbatim in state["messages"] (HumanMessage), so the synthesizer
        # still sees what the user actually typed.
        return {
            "query": rewritten,
            "query_variants": variants,
            "query_analyzer_degraded": degraded,
        }
    finally:
        span.end()
