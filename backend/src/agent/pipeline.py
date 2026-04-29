"""LangGraph 8-node pipeline - fully wired and compiled."""
from __future__ import annotations

import functools
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.nodes import (
    check_clarification,
    format_response,
    generate_response,
    guardrail_input,
    guardrail_output,
    handle_clarification,
    load_history,
    retrieve_context,
)
from src.agent.state import AgentState
from src.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from src.repositories.chunk_repository import ChunkRepository
from src.services.ai_model_resolver import AIModelResolver
from src.services.embedding_service_factory import EmbeddingServiceFactory
from src.services.guardrail_service import GuardrailService

logger = logging.getLogger(__name__)


def route(state: AgentState) -> str:
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "retrieve_context"


def route_after_guardrail_input(state: AgentState) -> str:
    """Short-circuit to END when the input guardrail blocks the query."""
    if state.get("error") == "guardrail_blocked_input":
        return END
    return "retrieve_context"


def build_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    workflow = StateGraph[AgentState](AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    _check_clarification = functools.partial(
        check_clarification,
        langfuse=langfuse,
    )
    _retrieve_context = functools.partial(
        retrieve_context,
        embedding_service_factory=embedding_service_factory,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    _generate_response = functools.partial(
        generate_response,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )

    workflow.add_node("load_history", _load_history)
    workflow.add_node("check_clarification", _check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)

    if guardrail_service is not None:
        _guardrail_input = functools.partial(
            guardrail_input,
            guardrail_service=guardrail_service,
            ai_model_resolver=ai_model_resolver,
        )
        _guardrail_output = functools.partial(
            guardrail_output,
            guardrail_service=guardrail_service,
            ai_model_resolver=ai_model_resolver,
        )
        workflow.add_node("guardrail_input", _guardrail_input)
        workflow.add_node("guardrail_output", _guardrail_output)

    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        route,
        {
            "handle_clarification": "handle_clarification",
            "retrieve_context": "guardrail_input" if guardrail_service is not None else "retrieve_context",
        },
    )
    workflow.add_edge("handle_clarification", END)

    if guardrail_service is not None:
        workflow.add_conditional_edges(
            "guardrail_input",
            route_after_guardrail_input,
            {
                END: END,
                "retrieve_context": "retrieve_context",
            },
        )

    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", "format_response")

    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


async def run_pipeline(
    *,
    compiled_graph: CompiledStateGraph[Any, Any, Any, Any],
    session_id: str,
    user_id: str,
    query: str,
    source_ids: list[str],
    trace_id: str,
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage  # noqa: PLC0415

    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    initial_state: AgentState = {
        "messages": [HumanMessage(content=query)],
        "source_ids": source_ids,
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": session_id,
        "user_id": user_id,
        "trace_id": trace_id,
        "query": query,
        "final_answer": None,
        "error": None,
        "sources": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }
    result = await compiled_graph.ainvoke(initial_state, config=config)
    return dict(result)
