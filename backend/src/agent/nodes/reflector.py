"""reflector — LangGraph node that critiques the synthesizer's draft answer.

Resolver slot: ``reflector``.  OFF by default
(``settings.PIPELINE_REFLECTOR_ENABLED=False``); when enabled the node
asks the LLM whether the draft answer faithfully addresses the user's
question given the retrieved chunks.

When the verdict is ``satisfied=False`` and the retry budget
(``state["reflector_retries"] < settings.PIPELINE_REFLECTOR_MAX_RETRIES``)
permits, the pipeline can re-loop through query_analyzer + retrieve +
synthesizer with the issues fed back as context.

Defensive: any LLM/parse error returns ``satisfied=True`` so the
pipeline never blocks on a reflector failure.

State writes:
* ``reflector_feedback: str | None`` — joined list of issues, or None.
* ``reflector_retries: int`` — incremented when a retry is requested.
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

_STAGE = "reflector"

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "reflector_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["satisfied", "issues"],
            "properties": {
                "satisfied": {"type": "boolean"},
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


async def _call_llm(
    *,
    query: str,
    answer: str,
    chunks: list[dict[str, Any]],
    ai_model_resolver: AIModelResolver,
) -> tuple[bool, list[str]]:
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    # Truncate chunk text to keep token budget bounded.
    context_excerpt = "\n\n".join(
        f"[{i}] {(c.get('text') or '')[:400]}"
        for i, c in enumerate(chunks[:5], start=1)
    )
    user_payload = (
        f"Question: {query}\n\n"
        f"Draft answer: {answer}\n\n"
        f"Context:\n{context_excerpt or '(none)'}"
    )
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_payload},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    satisfied = bool(payload.get("satisfied", True))
    issues_raw = payload.get("issues") or []
    issues = [str(i) for i in issues_raw if isinstance(i, str) and i.strip()]
    return satisfied, issues


async def reflect(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    langfuse: Langfuse,
    max_retries: int,
) -> dict[str, Any]:
    """Critique the draft answer; flag a retry when budget permits.

    Returns ``{}`` (no-op) when satisfied or when retries are exhausted.
    Otherwise returns ``{"reflector_feedback": <joined issues>,
    "reflector_retries": <incremented>}`` so the pipeline router can
    re-loop the retrieve+synthesize branch.
    """
    answer: str = (state.get("final_answer") or "").strip()
    query: str = (state.get("query") or "").strip()
    chunks: list[dict[str, Any]] = list(state.get("retrieved_chunks") or [])

    if not answer or not query:
        return {}

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={"answer_len": len(answer), "chunk_count": len(chunks)},
    )
    try:
        try:
            satisfied, issues = await _call_llm(
                query=query,
                answer=answer,
                chunks=chunks,
                ai_model_resolver=ai_model_resolver,
            )
        except Exception:  # noqa: BLE001 - degrade
            logger.warning(
                "reflector: LLM call failed — treating as satisfied",
                exc_info=True,
            )
            satisfied, issues = True, []

        retries_so_far: int = int(state.get("reflector_retries") or 0)
        span.update(
            output={
                "satisfied": satisfied,
                "issue_count": len(issues),
                "retries_so_far": retries_so_far,
            }
        )

        if satisfied or retries_so_far >= max_retries:
            logger.info(
                "reflector: terminal — satisfied=%s retries=%d/%d",
                satisfied,
                retries_so_far,
                max_retries,
            )
            return {"reflector_feedback": None}

        feedback = "; ".join(issues) if issues else "Answer flagged for retry."
        logger.info(
            "reflector: retry requested — feedback_len=%d retries=%d/%d",
            len(feedback),
            retries_so_far + 1,
            max_retries,
        )
        return {
            "reflector_feedback": feedback,
            "reflector_retries": retries_so_far + 1,
        }
    finally:
        span.end()
