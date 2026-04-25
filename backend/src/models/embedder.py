"""Embedder ORM model — admin-managed embedding endpoint records.

Each row represents a registered embedding model (provider+model+dimensions).
Sources and chunks both reference the embedder used to produce their vectors,
preserving the v1 invariant that there is exactly one active embedder
deployment-wide (enforced by a partial unique index).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class Embedder(Base, UUIDMixin, TimestampMixin):
    """Admin-managed embedder (embedding model endpoint) record."""

    __tablename__ = "embedders"

    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    extra_config: Mapped[dict[str, Any]] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default="{}", default=dict
    )
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    last_test_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ------------------------------------------------------------------ #
    # Security overrides                                                  #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Dict representation that omits the encrypted API key."""
        return {
            c.name: getattr(self, c.name)
            for c in self.__table__.columns
            if c.name != "api_key_encrypted"
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Embedder id={self.id} name={self.name!r} provider={self.provider!r}"
            f" model_id={self.model_id!r} dim={self.dimensions} active={self.is_active}>"
        )
