"""ORM models for chat sessions and messages."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression, func

from src.models.base import Base


class MessageRole(StrEnum):
    """Role of a participant in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSession(Base):
    """Represents a single conversation session for a user."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable since U15: lazy chat creation defers row insert until the
    # user sends their first message.  The titler still fills this in on the
    # first turn synchronously; a NULL title means "use the first user
    # message as a preview" on the sidebar fallback.
    title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=expression.false(),
        index=True,
    )
    source_ids: Mapped[list[str]] = mapped_column(
        _JSONB,
        nullable=False,
        default=list,
        server_default="'[]'::jsonb",
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ChatMessage(Base):
    """Represents a single message within a chat session."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="messagerole",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    # Phase 2: citation and streaming fields
    sources_cited: Mapped[list | None] = mapped_column(_JSONB, nullable=True)
    message_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default="normal"
    )
    is_partial: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    # User feedback on assistant messages — +1 thumbs up, -1 thumbs down.
    # NULL means no feedback given. Used by the admin analytics surface to
    # compute per-source average-feedback signals.
    feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Compact agentic activity summary (004-agentic-pipeline US5 / FR-018).
    # NULL for pre-feature rows and for non-agentic (v2 / legacy) turns; the
    # activity UI hides what is absent.  Column + 16 KiB CHECK guard added by
    # migration 0037; only application-generated narration is ever written here
    # (never raw row slices — security rule 5). The compact shape is built by
    # ``src.agent.activity_summary.build_activity_summary``.
    activity_summary: Mapped[dict | None] = mapped_column(_JSONB, nullable=True)

    session: Mapped[ChatSession] = relationship(
        "ChatSession",
        back_populates="messages",
    )
