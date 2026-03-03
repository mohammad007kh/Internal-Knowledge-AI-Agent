# T-051 â€” Document + Chunk ORM Models & Migration

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
RFC 7807 Problem Details â€” all non-2xx API responses
Docker Compose 9 services
```

## Goal
Define the `Document` and `Chunk` SQLAlchemy ORM models, register them with the
metadata base, and create the Alembic migration `0006_documents_chunks` that lays
down both tables plus the HNSW vector index on `chunks.embedding`.

---

## File 1 â€” `app/models/document.py`

```python
"""ORM model for a Document extracted from a Source."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.source import Source


class Document(UUIDMixin, TimestampMixin, Base):
    """
    Represents a single document extracted from a Source.

    A Source may produce many documents (e.g. one per page in a PDF or one per
    Confluence page).  After extraction the raw text is stored here; chunks are
    derived from documents and stored in the Chunk table.
    """

    __tablename__ = "documents"

    # FK â†’ sources; cascade delete so removing a source removes its documents.
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Raw extracted text (may be very large â€” stored as TEXT in PG).
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Arbitrary connector-supplied metadata: page number, URL, etc.
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Path in MinIO where the raw file/HTML is stored (nullable for DB connector).
    raw_storage_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    # Soft-delete flag â€” keeps the row for audit; excludes from queries via filter.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    source: Mapped["Source"] = relationship("Source", back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} source_id={self.source_id}>"
```

---

## File 2 â€” `app/models/chunk.py`

```python
"""ORM model for a text Chunk (with its vector embedding)."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.source import Source


EMBEDDING_DIM = 1536  # text-embedding-3-small


class Chunk(UUIDMixin, TimestampMixin, Base):
    """
    A chunk of text derived from a Document, with its vector embedding.

    source_id is denormalised here so similarity-search queries can filter by
    source_id without joining through documents (performance).
    """

    __tablename__ = "chunks"

    # FK â†’ documents; cascade delete.
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalised FK â†’ sources (avoids join in similarity search).
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The chunk text.
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Vector embedding (1536 dims for text-embedding-3-small).
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=False
    )

    # 0-based index of this chunk within its parent document.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Optional per-chunk metadata (e.g. page number, heading).
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    document: Mapped["Document"] = relationship(
        "Document", back_populates="chunks"
    )
    source: Mapped["Source"] = relationship("Source", back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Chunk id={self.id} document_id={self.document_id} "
            f"chunk_index={self.chunk_index}>"
        )
```

---

## File 3 â€” `app/models/source.py` (patch)

Add back-refs for the new relationships:

```python
# Add to the Source model (imports + relationship fields):

from app.models.document import Document  # noqa: F401  (TYPE_CHECKING guard optional)
from app.models.chunk import Chunk        # noqa: F401

# Inside class Source:
documents: Mapped[list["Document"]] = relationship(
    "Document",
    back_populates="source",
    cascade="all, delete-orphan",
    lazy="raise",
)
chunks: Mapped[list["Chunk"]] = relationship(
    "Chunk",
    back_populates="source",
    cascade="all, delete-orphan",
    lazy="raise",
)
```

---

## File 4 â€” `app/db/base.py` (patch)

Ensure both models are imported so Alembic autogenerate picks them up:

```python
# Existing imports:
from app.models.user import User          # noqa: F401
from app.models.source import Source      # noqa: F401

# Add:
from app.models.document import Document  # noqa: F401
from app.models.chunk import Chunk        # noqa: F401
```

---

## File 5 â€” `alembic/versions/0006_documents_chunks.py`

```python
"""create documents and chunks tables

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Enable pgvector extension (idempotent)                              #
    # ------------------------------------------------------------------ #
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------ #
    # documents table                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_storage_path", sa.String(500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"])

    # ------------------------------------------------------------------ #
    # chunks table                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_text", sa.Text, nullable=False),
        # pgvector column (1536 dims)
        sa.Column(
            "embedding",
            sa.Text,  # placeholder â€” replaced by raw SQL below
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Drop the placeholder Text column; add proper vector(1536) column.
    op.drop_column("chunks", "embedding")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding vector(1536) NOT NULL")

    # B-tree indexes on FK columns.
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_source_id", "chunks", ["source_id"])

    # HNSW index for cosine similarity search.
    op.execute(
        """
        CREATE INDEX chunks_embedding_hnsw_idx
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
    op.drop_index("ix_chunks_source_id", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_table("documents")
```

---

## Acceptance Criteria

1. `Document` and `Chunk` are importable from `app.models.document` and
   `app.models.chunk` respectively.
2. `EMBEDDING_DIM = 1536` is defined in `chunk.py` and matches the Vector column.
3. `Source.documents` and `Source.chunks` relationships exist with
   `cascade="all, delete-orphan"` and `lazy="raise"`.
4. `Document.chunks` relationship exists with `cascade="all, delete-orphan"`.
5. `alembic upgrade head` from migration `0005` applies `0006` without error.
6. After migration: `\d chunks` in psql shows `embedding vector(1536) not null`.
7. After migration: `SELECT indexname FROM pg_indexes WHERE tablename='chunks'`
   returns `chunks_embedding_hnsw_idx`.
8. `alembic downgrade -1` from `0006` drops both tables without error.
9. `app/db/base.py` imports both `Document` and `Chunk` so Alembic autogenerate
   includes them in `--autogenerate` diffs.
10. No circular import errors when running `python -c "from app.models import *"`.
