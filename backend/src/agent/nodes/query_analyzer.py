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
        "name": "query_variants",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["variants"],
            "properties": {
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


def _fallback(query: str) -> list[str]:
    """Single-variant fallback used on any LLM error."""
    return [query] if query else []


async def _call_llm(
    query: str,
    *,
    ai_model_resolver: AIModelResolver,
    reflector_feedback: str | None = None,
) -> list[str]:
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    # Slice E defect-2 fix: when the reflector flagged a retry, surface its
    # feedback to this LLM so the next batch of variants tries to address
    # the issues instead of re-running the same prompt verbatim.
    if reflector_feedback:
        user_content = (
            f"{query}\n\n"
            "Previous attempt was rejected because: "
            f"{reflector_feedback}. "
            "Generate query variants that would address this."
        )
    else:
        user_content = query
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
    variants_raw = payload.get("variants") or []
    variants: list[str] = []
    for v in variants_raw[:_MAX_VARIANTS]:
        if isinstance(v, str) and v.strip():
            variants.append(v.strip())
    if not variants:
        return _fallback(query)
    # Always ensure original query is one of the variants.
    if query and query not in variants:
        variants.insert(0, query)
        variants = variants[:_MAX_VARIANTS]
    return variants


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

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={"query": query, "has_reflector_feedback": bool(reflector_feedback)},
    )
    try:
        try:
            variants = await _call_llm(
                query,
                ai_model_resolver=ai_model_resolver,
                reflector_feedback=reflector_feedback,
            )
        except Exception:  # noqa: BLE001 - degrade
            logger.warning(
                "query_analyzer: LLM call failed, falling back to single variant",
                exc_info=True,
            )
            variants = _fallback(query)

        span.update(output={"variant_count": len(variants)})
        logger.info(
            "query_analyzer: produced %d variants for query_len=%d",
            len(variants),
            len(query),
        )
        return {"query_variants": variants}
    finally:
        span.end()
