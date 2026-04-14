"""guardrail — LangGraph nodes that evaluate input/output against company policies."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState

if TYPE_CHECKING:
    from src.services.guardrail_service import GuardrailService

logger = logging.getLogger(__name__)


async def guardrail_input(
    state: AgentState,
    *,
    guardrail_service: GuardrailService,
) -> dict[str, Any]:
    """Evaluate the user query against active company policies.

    If the query is blocked, sets ``state["error"]`` and
    ``state["final_answer"]`` to an appropriate message so the pipeline
    short-circuits at the generate step.
    """
    query: str = state.get("query", "").strip()
    if not query:
        return {}

    session_id_raw = state.get("session_id")
    session_id: uuid.UUID | None = None
    if session_id_raw:
        try:
            session_id = uuid.UUID(session_id_raw)
        except ValueError:
            pass

    decision = await guardrail_service.evaluate_input(query, session_id=session_id)
    if decision.blocked:
        logger.warning(
            "guardrail_input: blocked query for session=%s reason=%r",
            session_id_raw,
            decision.reason,
        )
        return {
            "error": "guardrail_blocked_input",
            "final_answer": (
                "I'm unable to process that request as it violates our usage policy."
            ),
        }
    return {}


async def guardrail_output(
    state: AgentState,
    *,
    guardrail_service: GuardrailService,
) -> dict[str, Any]:
    """Evaluate the generated answer against active company policies.

    If the answer is blocked, replaces ``state["final_answer"]`` with a safe
    fallback message.
    """
    answer: str = state.get("final_answer", "") or ""
    if not answer:
        return {}

    session_id_raw = state.get("session_id")
    session_id: uuid.UUID | None = None
    if session_id_raw:
        try:
            session_id = uuid.UUID(session_id_raw)
        except ValueError:
            pass

    decision = await guardrail_service.evaluate_output(answer, session_id=session_id)
    if decision.blocked:
        logger.warning(
            "guardrail_output: blocked response for session=%s reason=%r",
            session_id_raw,
            decision.reason,
        )
        return {
            "error": "guardrail_blocked_output",
            "final_answer": (
                "The generated response was blocked by our content policy. "
                "Please rephrase your question."
            ),
        }
    return {}
