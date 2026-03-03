"""Integration tests for retrieve_context node."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage

from src.agent.nodes.retrieve import retrieve_context
from src.agent.state import AgentState


def _make_state(
    query: str = "What is the leave policy?",
    source_ids: list[str] | None = None,
) -> AgentState:
    return {
        "messages": [HumanMessage(content=query)],
        "source_ids": source_ids or [str(uuid.uuid4())],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "query": query,
        "final_answer": None,
        "error": None,
    }


async def test_retriever_populates_chunks(
    mock_embedding_service: AsyncMock,
    mock_chunk_repository: AsyncMock,
    mock_db_session: AsyncMock,
    mock_langfuse: MagicMock,
) -> None:
    state = _make_state()
    result = await retrieve_context(
        state,
        embedding_service=mock_embedding_service,
        chunk_repository=mock_chunk_repository,
        db_session=mock_db_session,
        langfuse=mock_langfuse,
    )
    assert len(result["retrieved_chunks"]) == 2
    assert result["retrieved_chunks"][0]["text"] == "Employees get 12 weeks leave."


async def test_retriever_passes_source_ids_to_search(
    mock_embedding_service: AsyncMock,
    mock_chunk_repository: AsyncMock,
    mock_db_session: AsyncMock,
    mock_langfuse: MagicMock,
) -> None:
    sid = str(uuid.uuid4())
    state = _make_state(source_ids=[sid])
    await retrieve_context(
        state,
        embedding_service=mock_embedding_service,
        chunk_repository=mock_chunk_repository,
        db_session=mock_db_session,
        langfuse=mock_langfuse,
    )
    call_kwargs = mock_chunk_repository.similarity_search.call_args.kwargs
    assert call_kwargs["source_ids"] == [sid]


async def test_empty_results_propagated(
    mock_embedding_service: AsyncMock,
    mock_chunk_repository: AsyncMock,
    mock_db_session: AsyncMock,
    mock_langfuse: MagicMock,
) -> None:
    mock_chunk_repository.similarity_search.return_value = []
    state = _make_state()
    result = await retrieve_context(
        state,
        embedding_service=mock_embedding_service,
        chunk_repository=mock_chunk_repository,
        db_session=mock_db_session,
        langfuse=mock_langfuse,
    )
    assert result["retrieved_chunks"] == []
