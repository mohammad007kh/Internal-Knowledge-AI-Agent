"""ORM model for guardrail audit events."""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class GuardrailEvent(Base):
    """Audit record for every guardrail evaluation.

    Attributes:
        id: Primary key (UUID).
        direction: ``"input"`` or ``"output"``.
        text: The evaluated text.
        blocked: Whether the evaluation resulted in a block.
        reason: Human-readable reason (populated when blocked).
        triggered_policy_ids: JSON array of policy UUIDs that fired.
        session_id: Optional reference to the chat session.
        created_at: Event timestamp.
    """

    __tablename__ = "guardrail_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    direction: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    blocked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    triggered_policy_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
