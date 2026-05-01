"""Repositories for ChatSession and ChatMessage persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat import ChatMessage, ChatSession, MessageRole


class ChatSessionRepository:
    """CRUD operations for ChatSession rows."""

    def __init__(self, session: AsyncSession | None = None) -> None:  # noqa: ARG002
        # Session is injected per-call; constructor param kept for DI compatibility.
        pass

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        title: str = "New conversation",
    ) -> ChatSession:
        """Insert a new chat session and return the refreshed ORM object."""
        obj = ChatSession(user_id=user_id, title=title)
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def get(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
    ) -> ChatSession | None:
        """Fetch a single session by primary key; returns None if not found."""
        result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[ChatSession]:
        """Return all non-deleted sessions for a user, newest first."""
        result = await session.execute(
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.is_deleted.is_(False),
            )
            .order_by(ChatSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def rename(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
        title: str,
    ) -> ChatSession | None:
        """Update the title of a session. Returns updated object or None if not found."""
        obj = await self.get(session, session_id)
        if obj is None:
            return None
        obj.title = title
        await session.flush()
        await session.refresh(obj)
        return obj

    async def soft_delete(
        self,
        session: AsyncSession,
        session_id: uuid.UUID,
    ) -> None:
        """Mark a session as deleted without removing the row."""
        obj = await self.get(session, session_id)
        if obj:
            obj.is_deleted = True
            await session.flush()


class ChatMessageRepository:
    """CRUD operations for ChatMessage rows."""

    def __init__(self, session: AsyncSession | None = None) -> None:  # noqa: ARG002
        pass

    async def create(
        self,
        session: AsyncSession,
        *,
        chat_session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        message_type: str = "normal",
        is_partial: bool = False,
        sources_cited: list[dict] | None = None,
    ) -> ChatMessage:
        """Insert a single message and return the refreshed ORM object."""
        obj = ChatMessage(
            session_id=chat_session_id,
            role=role,
            content=content,
        )
        if hasattr(obj, "message_type"):
            obj.message_type = message_type
        if hasattr(obj, "is_partial"):
            obj.is_partial = is_partial
        if hasattr(obj, "sources_cited") and sources_cited is not None:
            obj.sources_cited = sources_cited
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def list_for_session(
        self,
        session: AsyncSession,
        chat_session_id: uuid.UUID,
    ) -> list[ChatMessage]:
        """Return all messages in a session ordered chronologically."""
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())
