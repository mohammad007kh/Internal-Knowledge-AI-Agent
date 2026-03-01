"""AgentState TypedDict for LangGraph pipeline."""
from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Shared state passed through every node in the pipeline."""

    messages: Annotated[list[BaseMessage], add_messages]
    source_ids: list[str]
    retrieved_chunks: list[dict[str, Any]]
    requires_clarification: bool
    clarification_question: str | None
    session_id: str
    user_id: str
    trace_id: str
    query: str
    final_answer: str | None
    error: str | None
