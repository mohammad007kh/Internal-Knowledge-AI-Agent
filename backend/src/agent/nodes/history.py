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

    # Sandbox sentinel: the admin sandbox endpoint runs the pipeline against
    # a single source without ever creating a chat_sessions row. Querying
    # the DB with an unparseable UUID would crash the pipeline; returning
    # the messages already seeded in state lets the caller drive history
    # via the request body instead. See
    # :mod:`src.services.chat_stream_service` for the contract.
    if session_id == "__sandbox__":
        return {"messages": state.get("messages", [])}

    chat_session = await chat_session_repository.get(db_session, UUID(session_id))
    # Cast both sides to str — chat_session.user_id is a UUID object on the
    # ORM (Mapped[uuid.UUID]) while state["user_id"] is a string injected by
    # chat.py at request time. The previous bare `!=` comparison was always
    # True (UUID != str) and silently dropped EVERY request into the
    # ownership-mismatch branch, which then returned source_ids=[] —
    # overwriting the resolved source_ids in the initial state. That's why
    # retrieve_context kept logging "empty source_ids" even after the
    # permission fix. The session-ownership check is also redundant here:
    # chat.py already enforces _assert_session_owner before invoking the
    # pipeline. We keep the not-found branch (defence in depth) but drop
    # the source_ids overwrite — load_history has no business touching
    # source_ids; that's a different node's concern.
    if chat_session is None or str(chat_session.user_id) != user_id:
        logger.warning(
            "load_history: session=%s not found or user_id mismatch (state=%s db=%s)",
            session_id,
            user_id,
            getattr(chat_session, "user_id", None),
        )
        return {"messages": []}

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
