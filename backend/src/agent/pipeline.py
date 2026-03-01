"""LangGraph StateGraph scaffold — 8-node RAG pipeline."""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from src.agent.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node stubs — will be fully implemented in later tasks
# ---------------------------------------------------------------------------


async def load_history(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Load conversation history from the database."""
    logger.debug("load_history: session_id=%s", state.get("session_id"))
    return {}


async def check_clarification(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Determine whether the query needs clarification before retrieval."""
    logger.debug("check_clarification: query=%s", state.get("query"))
    return {"requires_clarification": False, "clarification_question": None}


async def handle_clarification(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Return a clarification question to the user and stop the pipeline."""
    logger.debug(
        "handle_clarification: question=%s", state.get("clarification_question")
    )
    return {}


async def retrieve_context(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Retrieve relevant chunks from the vector store."""
    logger.debug(
        "retrieve_context: source_ids=%s", state.get("source_ids")
    )
    return {"retrieved_chunks": []}


async def generate_response(state: AgentState) -> dict:  # type: ignore[type-arg]
    """Generate a response using the LLM and retrieved context."""
    logger.debug("generate_response")
    return {}


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


def build_pipeline() -> StateGraph[AgentState]:
    """Wire up all nodes and edges and return the compiled graph."""
    workflow: StateGraph[AgentState] = StateGraph(AgentState)

    workflow.add_node("load_history", load_history)
    workflow.add_node("check_clarification", check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_response", generate_response)
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


# Module-level compiled graph — import and call get_pipeline() in consumers.
_graph = build_pipeline().compile()


def get_pipeline() -> object:
    """Return the module-level compiled LangGraph pipeline."""
    return _graph
