"""Chunk ORM model.

Implements T-051: Document + Chunk ORM Models.

Chunk
-----
Represents a text chunk derived from a Document, together with its pgvector
embedding.  Used for semantic similarity search during RAG retrieval.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.document import Document
    from src.models.source import Source

EMBEDDING_DIM = 1536  # text-embedding-3-small


class Chunk(UUIDMixin, TimestampMixin, Base):
    """A text chunk with its vector embedding derived from a Document."""

    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(  # type: ignore[type-arg]
        Vector(EMBEDDING_DIM), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )
    # Defensive FK — protects v1.1 transition to multi-embedder corpora.
    embedder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # -- relationships -------------------------------------------------------
    document: Mapped[Document] = relationship(
        "Document",
        back_populates="chunks",
        lazy="raise",
    )
    source: Mapped[Source] = relationship(
        "Source",
        back_populates="chunks",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Chunk id={self.id} document_id={self.document_id}"
            f" index={self.chunk_index}>"
        )
