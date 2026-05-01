"""ORM model stub for LLMConfiguration (FR-LLM-*)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class LLMConfiguration(Base, UUIDMixin, TimestampMixin):
    """Per-slot LLM provider configuration.

    Under v2 (AI_MODELS_V2) the ``ai_model_id`` FK is the canonical reference
    to the AIModel record holding the credential and base config.  The legacy
    inline columns (``provider`` / ``model_name`` / ``api_key_encrypted``) are
    kept nullable for backward compatibility and are dropped in revision R3.

    Attributes:
        slot_name: Logical identifier for this configuration slot (i.e. stage).
        ai_model_id: FK to the AIModel record this stage uses.
        temperature: Optional per-stage temperature override.
        max_tokens: Optional per-stage max-tokens override.
        custom_prompt: Optional per-stage system-prompt override.
        is_default: When ``True`` this slot is the system default.
    """

    __tablename__ = "llm_configurations"

    slot_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    ai_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_models.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Legacy columns (kept for migration window; nullable from R1 onward).
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Logging hygiene — must NEVER expose api_key_encrypted               #
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
            f"<LLMConfiguration id={self.id} slot={self.slot_name!r}"
            f" ai_model_id={self.ai_model_id}>"
        )
