"""ORM model stub for LLMConfiguration (FR-LLM-*)."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class LLMConfiguration(Base, UUIDMixin, TimestampMixin):
    """Per-slot LLM provider configuration.

    Attributes:
        slot_name: Logical identifier for this configuration slot.
        provider: LLM provider name (e.g. ``"openai"``).
        model_name: Model identifier within the provider.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum token budget for completions.
        api_key_encrypted: Encrypted API key stored as bytes.
        is_default: When ``True`` this slot is the system default.
    """

    __tablename__ = "llm_configurations"

    slot_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
