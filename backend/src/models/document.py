"""Document ORM model.

Implements T-051: Document + Chunk ORM Models.

Document
--------
Represents a raw document ingested from a Source.  Each Document may be split
into one or more Chunks for embedding and retrieval.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.chunk import Chunk
    from src.models.source import Source


class Document(UUIDMixin, TimestampMixin, Base):
    """A raw document ingested from a data source."""

    __tablename__ = "documents"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )
    raw_storage_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # -- relationships -------------------------------------------------------
    source: Mapped[Source] = relationship(
        "Source",
        back_populates="documents",
        lazy="raise",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} source_id={self.source_id}>"
