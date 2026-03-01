"""check_clarification and handle_clarification — LangGraph nodes."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from src.agent.state import AgentState

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

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


def _is_ambiguous(query: str) -> tuple[bool, str]:
    """Return (ambiguous, reason) for a query string."""
    stripped = query.strip()
    if len(stripped) < _MIN_QUERY_LENGTH:
        return (
            True,
            "Your question is too short to search accurately. Could you provide more detail?",
        )
    words = stripped.lower().split()
    if len(words) == 1 and words[0] in _AMBIGUOUS_SINGLE_WORDS:
        return (
            True,
            f"Your query '{stripped}' is ambiguous. What specifically would you like to know?",
        )
    return False, ""


async def check_clarification(state: AgentState, *, langfuse: Langfuse) -> dict:  # type: ignore[type-arg]
    """Decide whether the user query needs clarification before retrieval."""
    query: str = state.get("query", "").strip()
    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name="check_clarification",
        input={"query": query},
    )
    try:
        ambiguous, reason = _is_ambiguous(query)
        span.update(output={"requires_clarification": ambiguous, "reason": reason or "none"})
        logger.info(
            "check_clarification: query_len=%d requires=%s",
            len(query),
            ambiguous,
        )
        return {
            "requires_clarification": ambiguous,
            "clarification_question": reason if ambiguous else None,
        }
    finally:
        span.end()


async def handle_clarification(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Surface the clarification question to the user via interrupt() and resume."""
    question = (
        state.get("clarification_question")
        or "Could you please clarify your question?"
    )
    logger.info("handle_clarification: surfacing question to user")
    clarification_answer: str = interrupt(question)
    return {
        "messages": [HumanMessage(content=clarification_answer)],
        "query": clarification_answer,
        "requires_clarification": False,
        "clarification_question": None,
    }
