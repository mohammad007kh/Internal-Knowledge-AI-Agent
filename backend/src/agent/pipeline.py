"""LangGraph pipeline — v1 (legacy) and v2 (full 5-node) builders.

The active topology is selected by ``settings.PIPELINE_V2_ENABLED``:

* **v1** (legacy):  load_history → check_clarification(heuristic) →
  guardrail_input → retrieve_context → generate_response →
  format_response → guardrail_output → END
* **v2** (default): load_history → guardrail_input →
  check_clarification(LLM) → query_analyzer → source_router →
  (retrieve_context | text_to_query) → generate_response →
  [reflector → optional retry] → format_response → guardrail_output → END

Both share the same compiled-graph signature so callers do not need to
know which one is wired in — the env-flag rollback is a 30-second
backend restart away.
"""
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
    analyze_query,
    check_clarification,
    format_response,
    generate_response,
    guardrail_input,
    guardrail_output,
    handle_clarification,
    load_history,
    reflect,
    retrieve_context,
    route_sources,
    text_to_query,
)
from src.agent.state import AgentState
from src.core.config import settings
from src.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from src.repositories.chunk_repository import ChunkRepository
from src.repositories.source_repository import SourceRepository
from src.services.ai_model_resolver import AIModelResolver
from src.services.embedding_service_factory import EmbeddingServiceFactory
from src.services.guardrail_service import GuardrailService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routers — shared between v1 and v2 graphs
# ---------------------------------------------------------------------------


def _route_after_clarify(state: AgentState) -> str:
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "continue"


def _route_after_guardrail_input(state: AgentState) -> str:
    """Short-circuit to END when the input guardrail blocks the query."""
    if state.get("error") == "guardrail_blocked_input":
        return END
    return "continue"


def _route_after_router(state: AgentState) -> str:
    """Decide whether to fan out into text_to_query or skip directly to retrieve.

    Both branches are always run sequentially so the synthesizer sees
    chunks from each.  We only branch *off* text_to_query when no source
    was routed there to avoid an unnecessary LLM call.
    """
    if state.get("text_to_query_source_ids"):
        return "text_to_query"
    return "retrieve_context"


def _route_after_reflect(state: AgentState) -> str:
    """Re-loop into query_analyzer when the reflector flagged a retry."""
    if state.get("reflector_feedback"):
        return "query_analyzer"
    return "format_response"


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


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
    source_repository: SourceRepository | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the active pipeline.

    When ``settings.PIPELINE_V2_ENABLED`` is True the v2 graph is built
    (requires *source_repository*; pass-through to v1 when missing).
    Otherwise the v1 graph is built — kept verbatim for emergency
    rollback.
    """
    if settings.PIPELINE_V2_ENABLED and source_repository is not None:
        logger.info("pipeline: building v2 (PIPELINE_V2_ENABLED=True)")
        return _build_v2_pipeline(
            db_session=db_session,
            chunk_repository=chunk_repository,
            chat_session_repository=chat_session_repository,
            chat_message_repository=chat_message_repository,
            ai_model_resolver=ai_model_resolver,
            embedding_service_factory=embedding_service_factory,
            langfuse=langfuse,
            guardrail_service=guardrail_service,
            source_repository=source_repository,
        )
    logger.info(
        "pipeline: building v1 (PIPELINE_V2_ENABLED=%s, source_repository=%s)",
        settings.PIPELINE_V2_ENABLED,
        "set" if source_repository is not None else "missing",
    )
    return _build_v1_pipeline(
        db_session=db_session,
        chunk_repository=chunk_repository,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        ai_model_resolver=ai_model_resolver,
        embedding_service_factory=embedding_service_factory,
        langfuse=langfuse,
        guardrail_service=guardrail_service,
    )


# ---------------------------------------------------------------------------
# v1 — legacy single-shot pipeline (rollback target)
# ---------------------------------------------------------------------------


def _build_v1_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    workflow: StateGraph[AgentState] = StateGraph[AgentState](AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    # v1 uses the heuristic-only path — no resolver passed.
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
    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    if guardrail_service is not None:
        workflow.add_node(
            "guardrail_input",
            functools.partial(
                guardrail_input,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
        workflow.add_node(
            "guardrail_output",
            functools.partial(
                guardrail_output,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )

    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        _route_after_clarify,
        {
            "handle_clarification": "handle_clarification",
            "continue": "guardrail_input" if guardrail_service is not None else "retrieve_context",
        },
    )
    # Route the clarification text through guardrail_output so it gets
    # the same content-policy check as a normal answer.
    if guardrail_service is not None:
        workflow.add_edge("handle_clarification", "guardrail_output")
    else:
        workflow.add_edge("handle_clarification", END)

    if guardrail_service is not None:
        workflow.add_conditional_edges(
            "guardrail_input",
            _route_after_guardrail_input,
            {
                END: END,
                "continue": "retrieve_context",
            },
        )

    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", "format_response")

    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# v2 — full pipeline with the 5 newly-wired LLM nodes
# ---------------------------------------------------------------------------


def _build_v2_pipeline(
    *,
    db_session: AsyncSession,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    ai_model_resolver: AIModelResolver,
    embedding_service_factory: EmbeddingServiceFactory,
    langfuse: Langfuse,
    guardrail_service: GuardrailService | None,
    source_repository: SourceRepository,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    workflow: StateGraph[AgentState] = StateGraph[AgentState](AgentState)

    _load_history = functools.partial(
        load_history,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )
    _check_clarification = functools.partial(
        check_clarification,
        langfuse=langfuse,
        ai_model_resolver=ai_model_resolver,
    )
    _analyze_query = functools.partial(
        analyze_query,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    _route_sources = functools.partial(
        route_sources,
        ai_model_resolver=ai_model_resolver,
        db_session=db_session,
        source_repository=source_repository,
        langfuse=langfuse,
    )
    _retrieve_context = functools.partial(
        retrieve_context,
        embedding_service_factory=embedding_service_factory,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    _text_to_query = functools.partial(
        text_to_query,
        ai_model_resolver=ai_model_resolver,
        db_session=db_session,
        source_repository=source_repository,
        langfuse=langfuse,
    )
    _generate_response = functools.partial(
        generate_response,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    reflector_enabled = bool(settings.PIPELINE_REFLECTOR_ENABLED)
    _reflect = functools.partial(
        reflect,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
        max_retries=int(settings.PIPELINE_REFLECTOR_MAX_RETRIES),
    )

    workflow.add_node("load_history", _load_history)
    workflow.add_node("check_clarification", _check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("query_analyzer", _analyze_query)
    workflow.add_node("source_router", _route_sources)
    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("text_to_query", _text_to_query)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)

    if guardrail_service is not None:
        workflow.add_node(
            "guardrail_input",
            functools.partial(
                guardrail_input,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
        workflow.add_node(
            "guardrail_output",
            functools.partial(
                guardrail_output,
                guardrail_service=guardrail_service,
                ai_model_resolver=ai_model_resolver,
            ),
        )
    if reflector_enabled:
        workflow.add_node("reflector", _reflect)

    # Edges -----------------------------------------------------------------
    # Slice E defect-3 fix (V2 ONLY): guardrail_input must run BEFORE
    # check_clarification so a hostile / PII-laden query is blocked before
    # we burn an LLM call deciding whether to clarify it.  V1 keeps its
    # historical order (clarify first) — see _build_v1_pipeline.
    workflow.add_edge(START, "load_history")
    if guardrail_service is not None:
        workflow.add_edge("load_history", "guardrail_input")
        workflow.add_conditional_edges(
            "guardrail_input",
            _route_after_guardrail_input,
            {
                END: END,
                "continue": "check_clarification",
            },
        )
    else:
        workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        _route_after_clarify,
        {
            "handle_clarification": "handle_clarification",
            "continue": "query_analyzer",
        },
    )
    # Route the clarification text through guardrail_output so it gets the
    # same content-policy check as a normal answer (matches v1 behaviour).
    if guardrail_service is not None:
        workflow.add_edge("handle_clarification", "guardrail_output")
    else:
        workflow.add_edge("handle_clarification", END)

    workflow.add_edge("query_analyzer", "source_router")
    workflow.add_conditional_edges(
        "source_router",
        _route_after_router,
        {
            "text_to_query": "text_to_query",
            "retrieve_context": "retrieve_context",
        },
    )
    # text_to_query and retrieve_context both feed the synthesizer.  When
    # text_to_query fired we still want vector retrieval for non-DB
    # sources; chain it through retrieve_context next.
    workflow.add_edge("text_to_query", "retrieve_context")
    workflow.add_edge("retrieve_context", "generate_response")

    if reflector_enabled:
        workflow.add_edge("generate_response", "reflector")
        workflow.add_conditional_edges(
            "reflector",
            _route_after_reflect,
            {
                "query_analyzer": "query_analyzer",
                "format_response": "format_response",
            },
        )
    else:
        workflow.add_edge("generate_response", "format_response")

    if guardrail_service is not None:
        workflow.add_edge("format_response", "guardrail_output")
        workflow.add_edge("guardrail_output", END)
    else:
        workflow.add_edge("format_response", END)

    return workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Convenience runner — used by tests.  Production goes via chat.py's
# astream_events directly.
# ---------------------------------------------------------------------------


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
        "query_variants": [],
        "selected_source_ids": [],
        "text_to_query_source_ids": [],
        "generated_sql": {},
        "reflector_feedback": None,
        "reflector_retries": 0,
    }
    result = await compiled_graph.ainvoke(initial_state, config=config)
    return dict(result)
