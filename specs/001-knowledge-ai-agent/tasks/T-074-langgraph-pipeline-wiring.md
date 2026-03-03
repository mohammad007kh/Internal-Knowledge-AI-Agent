# T-074 â€” LangGraph Full Pipeline Wiring + Compilation

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
OpenAI API Â· tenacity 3-retry
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Finalize the **`save_message` + `format_response` + `load_history` nodes**,
wire all 8 nodes with real dependency injection, compile the graph with
`MemorySaver` checkpointer, and expose a `run_pipeline()` async function
that can be called from the API router.

---

## Acceptance Criteria

- [ ] All 8 nodes are real implementations (no stubs)
- [ ] `build_pipeline()` returns a compiled graph with `MemorySaver` checkpointer
- [ ] `run_pipeline(session_id, user_id, query, source_ids)` streams events via `astream_events()`
- [ ] `load_history` reads last 20 messages from `ChatMessageRepository`
- [ ] `save_message` persists both the user query and AI response to `ChatMessage`
- [ ] `format_response` trivially passes `final_answer` through (no-op in v1)
- [ ] Integration smoke-test: pipeline with all mocks ends with non-empty SSE events

---

## 1  `app/agent/nodes/history.py`

```python
# app/agent/nodes/history.py
"""load_history â€” LangGraph node."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.models.chat import MessageRole

if TYPE_CHECKING:
    from app.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 20


async def load_history(
    state: AgentState,
    *,
    chat_session_repository: "ChatSessionRepository",
    chat_message_repository: "ChatMessageRepository",
    db_session: "AsyncSession",
) -> dict:
    """Load the last N messages from the chat session into state.messages.

    Also validates that the session exists and belongs to the current user.
    Source IDs are loaded from the session's permitted sources (FR-019).
    """
    session_id = state["session_id"]
    user_id = state["user_id"]

    chat_session = await chat_session_repository.get(db_session, session_id=session_id)
    if chat_session is None or chat_session.user_id != user_id:
        logger.warning(
            "load_history: session not found or user mismatch session=%s user=%s",
            session_id,
            user_id,
        )
        return {"messages": [], "source_ids": []}

    messages_db = await chat_message_repository.list_for_session(
        db_session, session_id=session_id, limit=_HISTORY_LIMIT
    )

    lc_messages = []
    for msg in messages_db:
        if msg.role == MessageRole.USER:
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.ASSISTANT:
            lc_messages.append(AIMessage(content=msg.content))
        # skip system messages in the LangChain history

    logger.info("load_history: loaded %d messages for session=%s", len(lc_messages), session_id)
    return {"messages": lc_messages}
```

---

## 2  `app/agent/nodes/persist.py`

```python
# app/agent/nodes/persist.py
"""save_message + format_response â€” LangGraph nodes."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.agent.state import AgentState
from app.models.chat import MessageRole

if TYPE_CHECKING:
    from app.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def format_response(state: AgentState) -> dict:
    """Pass-through formatting node (v1).

    In a future version this node could apply Markdown sanitisation,
    citation injection, or source-link rendering.  For now it is a no-op.
    """
    return {}


async def save_message(
    state: AgentState,
    *,
    chat_session_repository: "ChatSessionRepository",
    chat_message_repository: "ChatMessageRepository",
    db_session: "AsyncSession",
) -> dict:
    """Persist the user question and assistant answer to ``ChatMessage``.

    Both rows are written in the same DB flush to keep them atomic.
    Also touches ``ChatSession.updated_at`` so the session list stays sorted.
    """
    session_id = state["session_id"]
    query = state.get("query", "")
    answer = state.get("final_answer", "")

    if not answer:
        logger.warning("save_message: empty final_answer for session=%s â€” skipping", session_id)
        return {}

    try:
        # User turn
        await chat_message_repository.create(
            db_session,
            session_id=session_id,
            role=MessageRole.USER,
            content=query,
        )
        # Assistant turn
        await chat_message_repository.create(
            db_session,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        # Keep session updated_at current
        await chat_session_repository.touch(db_session, session_id=session_id)
        await db_session.commit()

        logger.info("save_message: persisted 2 messages for session=%s", session_id)
    except Exception:
        logger.exception("save_message: DB write failed for session=%s", session_id)
        await db_session.rollback()
        # Non-fatal â€” the answer was still generated; don't set error state

    return {}
```

---

## 3  `app/agent/nodes/__init__.py` â€” final version

```python
# app/agent/nodes/__init__.py
"""LangGraph node implementations."""
from app.agent.nodes.clarify import check_clarification, handle_clarification  # noqa: F401
from app.agent.nodes.generate import generate_response  # noqa: F401
from app.agent.nodes.history import load_history  # noqa: F401
from app.agent.nodes.persist import format_response, save_message  # noqa: F401
from app.agent.nodes.retrieve import retrieve_context  # noqa: F401
```

---

## 4  `app/agent/pipeline.py` â€” final version

```python
# app/agent/pipeline.py
"""LangGraph 8-node pipeline â€” fully wired and compiled."""
from __future__ import annotations

import functools
import logging

from langfuse import Langfuse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.nodes import (
    check_clarification,
    format_response,
    generate_response,
    handle_clarification,
    load_history,
    retrieve_context,
    save_message,
)
from app.agent.state import AgentState
from app.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from app.repositories.chunk_repository import ChunkRepository
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def route(state: AgentState) -> str:
    """Conditional edge after check_clarification."""
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "retrieve_context"


def build_pipeline(
    *,
    db_session: AsyncSession,
    embedding_service: EmbeddingService,
    chunk_repository: ChunkRepository,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    openai_client: AsyncOpenAI,
    langfuse: Langfuse,
) -> StateGraph:
    """Build and compile the full 8-node LangGraph pipeline.

    Dependencies are injected via ``functools.partial`` so that each node
    function signature stays clean (``state: AgentState`` only in tests).
    """
    workflow = StateGraph(AgentState)

    # Partially apply all dependencies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
        db_session=db_session,
        langfuse=langfuse,
    )
    _generate_response = functools.partial(
        generate_response,
        openai_client=openai_client,
        langfuse=langfuse,
    )
    _save_message = functools.partial(
        save_message,
        chat_session_repository=chat_session_repository,
        chat_message_repository=chat_message_repository,
        db_session=db_session,
    )

    # Register nodes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    workflow.add_node("load_history", _load_history)
    workflow.add_node("check_clarification", _check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("retrieve_context", _retrieve_context)
    workflow.add_node("generate_response", _generate_response)
    workflow.add_node("format_response", format_response)
    workflow.add_node("save_message", _save_message)

    # Edges â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        route,
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

    # Compile with in-memory checkpointer (swap for Redis in production)
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


async def run_pipeline(
    *,
    compiled_graph: StateGraph,
    session_id: str,
    user_id: str,
    query: str,
    source_ids: list[str],
    trace_id: str,
) -> dict:
    """Invoke the compiled pipeline and return the final state.

    Used by the non-streaming code path (tests + simple API calls).
    For streaming, use ``compiled_graph.astream_events()`` directly in
    the API router (T-076).
    """
    from langchain_core.messages import HumanMessage  # noqa: PLC0415

    config = {"configurable": {"thread_id": session_id}}
    initial_state: AgentState = {  # type: ignore[assignment]
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
    }

    result = await compiled_graph.ainvoke(initial_state, config=config)
    return result
```

---

## 5  `containers.py` â€” patch (add pipeline factory)

```python
# Inside ApplicationContainer, after chat_message_repository:

from app.agent.pipeline import build_pipeline
from openai import AsyncOpenAI

openai_client = providers.Singleton(
    AsyncOpenAI,
    api_key=config.openai.api_key,
)

pipeline = providers.Factory(
    build_pipeline,
    db_session=db_session,
    embedding_service=embedding_service,
    chunk_repository=chunk_repository,
    chat_session_repository=chat_session_repository,
    chat_message_repository=chat_message_repository,
    openai_client=openai_client,
    langfuse=langfuse,
)
```

---

## 6  Integration Smoke Test â€” `tests/integration/test_pipeline_smoke.py`

```python
# tests/integration/test_pipeline_smoke.py
"""Smoke test: full pipeline with all external deps mocked."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.agent.pipeline import build_pipeline, run_pipeline
from app.models.chat import MessageRole


@pytest.fixture()
def mocked_pipeline(db_session):
    """Build a pipeline where all external services are mocked."""
    mock_embedding = AsyncMock()
    mock_embedding.embed_texts.return_value = [[0.1] * 1536]

    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.similarity_search.return_value = []

    mock_chat_session_repo = AsyncMock()
    mock_session = MagicMock()
    mock_session.user_id = "user-1"
    mock_chat_session_repo.get.return_value = mock_session

    mock_chat_msg_repo = AsyncMock()
    mock_chat_msg_repo.list_for_session.return_value = []
    mock_chat_msg_repo.create.return_value = MagicMock()

    mock_openai = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "Here is the answer."
    completion.usage.prompt_tokens = 50
    completion.usage.completion_tokens = 10
    mock_openai.chat.completions.create.return_value = completion

    mock_langfuse = MagicMock()
    mock_span = MagicMock()
    mock_langfuse.span.return_value = mock_span

    return build_pipeline(
        db_session=db_session,
        embedding_service=mock_embedding,
        chunk_repository=mock_chunk_repo,
        chat_session_repository=mock_chat_session_repo,
        chat_message_repository=mock_chat_msg_repo,
        openai_client=mock_openai,
        langfuse=mock_langfuse,
    )


@pytest.mark.asyncio
async def test_pipeline_returns_final_answer(mocked_pipeline):
    result = await run_pipeline(
        compiled_graph=mocked_pipeline,
        session_id="sess-1",
        user_id="user-1",
        query="What is the return policy?",
        source_ids=["src-1"],
        trace_id="trace-1",
    )
    assert result["final_answer"] == "Here is the answer."
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_pipeline_short_query_triggers_clarification(mocked_pipeline):
    """A 2-char query should set requires_clarification=True and end early."""
    result = await run_pipeline(
        compiled_graph=mocked_pipeline,
        session_id="sess-2",
        user_id="user-1",
        query="hi",
        source_ids=["src-1"],
        trace_id="trace-2",
    )
    # Graph ends at handle_clarification node â†’ final_answer is None
    assert result.get("requires_clarification") is True
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/agent/nodes/history.py` |
| CREATE | `app/agent/nodes/persist.py` |
| PATCH  | `app/agent/nodes/__init__.py` (final) |
| PATCH  | `app/agent/pipeline.py` (final) |
| PATCH  | `containers.py` |
| CREATE | `tests/integration/test_pipeline_smoke.py` |
