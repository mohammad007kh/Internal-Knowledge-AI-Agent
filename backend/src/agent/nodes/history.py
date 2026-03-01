"""load_history — LangGraph node."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.state import AgentState
from src.models.chat import MessageRole

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chat_repository import (
        ChatMessageRepository,
        ChatSessionRepository,
    )

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 20


async def load_history(
    state: AgentState,
    *,
    chat_session_repository: ChatSessionRepository,
    chat_message_repository: ChatMessageRepository,
    db_session: AsyncSession,
) -> dict[str, Any]:
    """Load last N messages for the session.

    Validates the session belongs to the user before fetching messages.
    Returns ``{messages: [...]}`` (empty list when session is invalid or
    not found).
    """
    session_id = state["session_id"]
    user_id = state["user_id"]

    chat_session = await chat_session_repository.get(db_session, UUID(session_id))
    if chat_session is None or chat_session.user_id != user_id:
        logger.warning(
            "load_history: session=%s not found or user_id mismatch (user=%s)",
            session_id,
            user_id,
        )
        return {"messages": [], "source_ids": []}

    messages_db = await chat_message_repository.list_for_session(
        db_session,
        UUID(session_id),
    )

    lc_messages: list[HumanMessage | AIMessage] = []
    for msg in messages_db:
        if msg.role == MessageRole.USER:
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.ASSISTANT:
            lc_messages.append(AIMessage(content=msg.content))

    return {"messages": lc_messages}
