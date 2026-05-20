"""AgentState TypedDict for LangGraph pipeline."""
from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state passed through every node in the pipeline.

    ``total=False`` so v2 nodes can omit fields they do not own without
    breaking v1's stricter contract.  Every consumer must guard reads
    with ``state.get(...)``.
    """

    # --- v1 / always-present ------------------------------------------------
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
    sources: list[dict[str, Any]]
    total_input_tokens: int
    total_output_tokens: int
    # --- v2 additions -------------------------------------------------------
    query_variants: list[str]
    selected_source_ids: list[str]
    text_to_query_source_ids: list[str]
    generated_sql: dict[str, str]
    reflector_feedback: str | None
    reflector_retries: int
    query_analyzer_degraded: bool
