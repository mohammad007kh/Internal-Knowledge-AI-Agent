"""AIModel ORM model — admin-managed LLM endpoint records.

Each row represents a registered LLM provider+model+credential triple.
Pipeline stages reference these via :class:`LLMConfiguration.ai_model_id`.

Security:
- ``api_key_encrypted`` is Fernet ciphertext.  ``to_dict`` and ``__repr__``
  override the base helpers to omit the field — never log it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class AIModel(Base, UUIDMixin, TimestampMixin):
    """Admin-managed AI model (LLM endpoint) record."""

    __tablename__ = "ai_models"

    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    extra_config: Mapped[dict[str, Any]] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default="{}", default=dict
    )
    default_temperature: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.7", default=0.7
    )
    default_max_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="2048", default=2048
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default="{}", default=dict
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
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
    # Security overrides — must NEVER expose api_key_encrypted in logs    #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation that omits the encrypted API key."""
        return {
            c.name: getattr(self, c.name)
            for c in self.__table__.columns
            if c.name != "api_key_encrypted"
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AIModel id={self.id} name={self.name!r}"
            f" provider={self.provider!r} model_id={self.model_id!r}>"
        )
