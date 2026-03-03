"""SQLAlchemy model for system health events — FR-033."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SystemHealthEvent(Base):
    """Persisted record of a worker component life-cycle event.

    event_type values:
        - ``crash``            — component reported an unhandled fault
        - ``restart_attempt``  — supervisor dispatched a restart (attempt N)
        - ``restart_ok``       — component came back healthy
        - ``restart_failed``   — supervisor exhausted MAX_RESTART_ATTEMPTS
    """

    __tablename__ = "system_health_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    component_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
