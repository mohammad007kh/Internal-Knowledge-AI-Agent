"""persist — LangGraph nodes for message persistence and response formatting."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.agent.state import AgentState
from src.models.chat import MessageRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chat_repository import (
        ChatMessageRepository,
        ChatSessionRepository,
    )

logger = logging.getLogger(__name__)


async def format_response(state: AgentState) -> dict[str, Any]:
    """Format / post-process the final answer and extract source citations.

    Builds a deduplicated list of source documents from the retrieved chunks
    and stores it in ``state["sources"]`` so the API layer can include it in
    the done event sent to the frontend.
    """
    chunks: list[dict[str, Any]] = state.get("retrieved_chunks", [])

    seen_source_ids: set[str] = set()
    sources: list[dict[str, Any]] = []

    for chunk in chunks:
        source_id = str(chunk.get("source_id", ""))
        if not source_id or source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        sources.append(
            {
                "source_id": source_id,
                "title": chunk.get("document_title") or chunk.get("source_name") or source_id,
                "page": chunk.get("page_number"),
            }
        )

    logger.debug("format_response: extracted %d unique sources", len(sources))
    return {"sources": sources}


async def save_message(
    state: AgentState,
    *,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    db_session: AsyncSession,
) -> dict[str, Any]:
    """Persist the user question and assistant answer to ``ChatMessage``.

    Both rows are written in the same DB flush to keep them atomic.
    Also touches ``ChatSession.updated_at`` so the session list stays sorted.
    """
    session_id = state["session_id"]
    query = state.get("query", "")
    answer = state.get("final_answer", "")

    if not answer:
        logger.warning(
            "save_message: empty final_answer for session=%s — skipping",
            session_id,
        )
        return {}

    try:
        # User turn
        await chat_message_repository.create(
            db_session,
            chat_session_id=UUID(session_id),
            role=MessageRole.USER,
            content=query,
        )
        # Assistant turn
        await chat_message_repository.create(
            db_session,
            chat_session_id=UUID(session_id),
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        await db_session.commit()

        logger.info(
            "save_message: persisted 2 messages for session=%s",
            session_id,
        )
    except Exception:
        logger.exception(
            "save_message: DB write failed for session=%s",
            session_id,
        )
        await db_session.rollback()
        # Non-fatal — the answer was still generated; don't set error state

    return {}
