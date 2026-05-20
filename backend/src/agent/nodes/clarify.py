"""check_clarification and handle_clarification — LangGraph nodes.

In pipeline v2 :func:`check_clarification` resolves the
``"clarification_detector"`` slot via :class:`AIModelResolver` and asks
the LLM for a structured ``{"needs_clarification": bool, "question":
str | null}`` verdict.  On any LLM error the node degrades to the legacy
heuristic (length + ambiguous-pronoun list) so a transient OpenAI
outage never hard-fails the pipeline.

The legacy heuristic is also the only path used when the v1 builder is
selected via ``settings.PIPELINE_V2_ENABLED=False`` — the resolver and
``ai_model_resolver`` keyword are optional for backwards compatibility
with the v1 partial-application in :mod:`src.agent.pipeline`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "clarification_detector"
_MIN_QUERY_LENGTH = 5
_AMBIGUOUS_SINGLE_WORDS = frozenset(
    {
        "it",
        "that",
        "this",
        "them",
        "they",
        "he",
        "she",
        "what",
        "how",
        "why",
        "when",
        "where",
    }
)

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "clarification_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["needs_clarification", "question"],
            "properties": {
                "needs_clarification": {"type": "boolean"},
                "question": {"type": ["string", "null"]},
            },
        },
    },
}


@dataclass(frozen=True)
class ClarificationDecision:
    """Immutable verdict returned by either the LLM or the heuristic."""

    needs_clarification: bool
    question: str | None


def _heuristic_decision(query: str) -> ClarificationDecision:
    """Fallback heuristic — preserved verbatim from the v1 implementation."""
    stripped = query.strip()
    if len(stripped) < _MIN_QUERY_LENGTH:
        return ClarificationDecision(
            needs_clarification=True,
            question=(
                "Your question is too short to search accurately. "
                "Could you provide more detail?"
            ),
        )
    words = stripped.lower().split()
    if len(words) == 1 and words[0] in _AMBIGUOUS_SINGLE_WORDS:
        return ClarificationDecision(
            needs_clarification=True,
            question=(
                f"Your query '{stripped}' is ambiguous. "
                "What specifically would you like to know?"
            ),
        )
    return ClarificationDecision(needs_clarification=False, question=None)


async def _llm_decision(
    query: str,
    *,
    ai_model_resolver: AIModelResolver,
) -> ClarificationDecision:
    """Resolve the slot, call the LLM, return a structured verdict."""
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    needs = bool(payload.get("needs_clarification", False))
    question_raw = payload.get("question")
    question: str | None = (
        str(question_raw).strip() if isinstance(question_raw, str) and question_raw.strip() else None
    )
    if needs and question is None:
        question = "Could you please clarify your question?"
    if not needs:
        question = None
    return ClarificationDecision(needs_clarification=needs, question=question)


async def check_clarification(
    state: AgentState,
    *,
    langfuse: Langfuse,
    ai_model_resolver: AIModelResolver | None = None,
) -> dict[str, Any]:
    """Decide whether the user query needs clarification before retrieval.

    When *ai_model_resolver* is supplied (pipeline v2) the LLM is asked
    via the ``clarification_detector`` slot.  On any LLM/parse error the
    node falls back to the legacy heuristic — never hard-fails.
    """
    query: str = state.get("query", "").strip()
    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name="check_clarification",
        input={"query": query},
    )
    try:
        decision: ClarificationDecision
        used_llm = False
        if ai_model_resolver is not None:
            try:
                decision = await _llm_decision(
                    query, ai_model_resolver=ai_model_resolver
                )
                used_llm = True
            except Exception:  # noqa: BLE001 - degrade to heuristic
                logger.warning(
                    "check_clarification: LLM call failed, using heuristic",
                    exc_info=True,
                )
                decision = _heuristic_decision(query)
        else:
            decision = _heuristic_decision(query)

        span.update(
            output={
                "requires_clarification": decision.needs_clarification,
                "reason": decision.question or "none",
                "used_llm": used_llm,
            }
        )
        logger.info(
            "check_clarification: query_len=%d requires=%s used_llm=%s",
            len(query),
            decision.needs_clarification,
            used_llm,
        )
        return {
            "requires_clarification": decision.needs_clarification,
            "clarification_question": decision.question,
        }
    finally:
        span.end()


async def handle_clarification(state: AgentState) -> dict[str, Any]:
    """Surface the LLM-generated clarification question as the final answer.

    LangGraph's ``interrupt()`` is not picked up inside ``astream_events``
    streaming consumers under ``MemorySaver`` — it pauses silently,
    leaving ``final_answer=None``, which now trips the empty-answer
    guard added in ``chat.py``.  Returning the question as a normal
    terminal answer makes the semantics consistent with every other
    terminal node in the graph: the user sees the question text, can
    reply with their next message, and the assistant row gets persisted
    normally.
    """
    question = (
        state.get("clarification_question")
        or "Could you please clarify your question?"
    )
    logger.info("handle_clarification: returning question as terminal answer")
    return {"final_answer": question, "sources": []}
