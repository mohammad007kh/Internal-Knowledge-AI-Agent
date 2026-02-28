"""documents and chunks tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-02-28 00:00:00.000000

Implements T-051: Document + Chunk ORM Models.

Tables
------
* documents — raw extracted text per source
* chunks    — text chunks with pgvector embeddings (1536-dim, text-embedding-3-small)

Notes
-----
* pgvector extension is created here if it does not already exist.
* The ``embedding`` column cannot be expressed as a plain SA type during
  ``op.create_table`` (pgvector may not be importable in all migration
  environments), so it is added via a raw ``ALTER TABLE`` statement after
  the table scaffold is created from a temporary ``TEXT`` placeholder.
* The HNSW index is also created via raw SQL because
  ``op.create_index`` does not support the ``USING hnsw ... WITH (...)``
  syntax.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0007"
down_revision: str = "0006"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Enable pgvector extension
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 2. documents table
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("raw_storage_path", sa.String(length=500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_documents_source_id",
        "documents",
        ["source_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 3. chunks table  (embedding scaffolded as TEXT placeholder)
    # ------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        # Temporary TEXT placeholder — replaced below via ALTER TABLE
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # 4. Replace placeholder embedding column with vector(1536)
    # ------------------------------------------------------------------
    op.drop_column("chunks", "embedding")
    op.execute(
        "ALTER TABLE chunks ADD COLUMN embedding vector(1536) NOT NULL"
    )

    # ------------------------------------------------------------------
    # 5. B-tree indexes on FK columns
    # ------------------------------------------------------------------
    op.create_index(
        "ix_chunks_document_id",
        "chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunks_source_id",
        "chunks",
        ["source_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 6. HNSW index for cosine-similarity search (pgvector)
    # ------------------------------------------------------------------
    op.execute(
        "CREATE INDEX chunks_embedding_hnsw_idx "
        "ON chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    # Drop HNSW index first (not tracked by op.drop_index)
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")

    op.drop_index("ix_chunks_source_id", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_table("documents")
