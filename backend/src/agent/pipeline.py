"""LangGraph StateGraph scaffold — 8-node RAG pipeline."""
from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.agent.nodes.clarify import check_clarification, handle_clarification
from src.agent.nodes.generate import generate_response
from src.agent.nodes.retrieve import retrieve_context
from src.agent.state import AgentState

if TYPE_CHECKING:
    from langfuse import Langfuse
    from openai import AsyncOpenAI
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chunk_repository import ChunkRepository
    from src.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node stubs — will be fully implemented in later tasks
# ---------------------------------------------------------------------------


async def load_history(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Load conversation history from the database."""
    logger.debug("load_history: session_id=%s", state.get("session_id"))
    return {}


# check_clarification and handle_clarification are imported from src.agent.nodes.clarify
# generate_response is imported from src.agent.nodes.generate


async def format_response(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Format and clean the raw LLM output."""
    logger.debug("format_response")
    return {}


async def save_message(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Persist the assistant message to the chat_messages table."""
    logger.debug("save_message: session_id=%s", state.get("session_id"))
    return {}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_after_clarification_check(state: AgentState) -> str:
    """Branch to clarification handler or straight to retrieval."""
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "retrieve_context"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_pipeline(
    *,
    embedding_service: EmbeddingService,
    chunk_repository: ChunkRepository,
    db_session: AsyncSession,
    langfuse: Langfuse,
    openai_client: AsyncOpenAI,
) -> StateGraph[AgentState]:
    """Wire up all nodes and edges and return the compiled graph."""
    workflow: StateGraph[AgentState] = StateGraph(AgentState)

    bound_retrieve = partial(
        retrieve_context,
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    bound_generate = partial(
        generate_response,
        openai_client=openai_client,
        langfuse=langfuse,
    )

    workflow.add_node("load_history", load_history)
    workflow.add_node("check_clarification", check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("retrieve_context", bound_retrieve)
    workflow.add_node("generate_response", bound_generate)
    workflow.add_node("format_response", format_response)
    workflow.add_node("save_message", save_message)

    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")

    workflow.add_conditional_edges(
        "check_clarification",
        _route_after_clarification_check,
        {
            "handle_clarification": "handle_clarification",
            "retrieve_context": "retrieve_context",
        },
    )

    workflow.add_edge("handle_clarification", END)
    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", "format_response")
    workflow.add_edge("format_response", "save_message")
    workflow.add_edge("save_message", END)

    return workflow


def get_pipeline(
    *,
    embedding_service: EmbeddingService,
    chunk_repository: ChunkRepository,
    db_session: AsyncSession,
    langfuse: Langfuse,
    openai_client: AsyncOpenAI,
) -> object:
    """Compile and return a LangGraph pipeline bound to the provided dependencies."""
    return build_pipeline(
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
        openai_client=openai_client,
    ).compile()
