"""add_schema_study

Phase 1 — Deliverable #1 of the DB-source studying-agent.

Creates:

* ``schema_studies`` — one row per study run.
* ``schema_study_phases`` — one row per phase per study.
* Three new columns on ``sources``: ``schema_status``, ``drift_signal_count``,
  ``last_studied_at``, plus a partial index on ``schema_status``.

Revision ID: 0027
Revises:     0026
Create Date: 2026-05-09

Renumbered from 0025 to 0027 — the original 0025 slot was already taken by
``0025_add_deleted_at_to_sources`` and 0026 by
``0026_documents_chunks_timestamp_defaults``. Inserting after 0026 keeps the
linear chain head-only.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. schema_studies
    # ------------------------------------------------------------------
    op.create_table(
        "schema_studies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'QUEUED'"),
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "schema_document_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("agent_version", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_error_phase", sa.String(length=32), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_schema_studies_source_id",
        "schema_studies",
        ["source_id"],
    )
    op.create_index(
        "ix_schema_studies_state",
        "schema_studies",
        ["state"],
    )

    # ------------------------------------------------------------------
    # 2. schema_study_phases
    # ------------------------------------------------------------------
    op.create_table(
        "schema_study_phases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "study_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schema_studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_key", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("progress_n", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_schema_study_phases_study_phase",
        "schema_study_phases",
        ["study_id", "phase"],
    )

    # ------------------------------------------------------------------
    # 3. New columns on sources
    # ------------------------------------------------------------------
    op.add_column(
        "sources",
        sa.Column("schema_status", sa.String(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column(
            "drift_signal_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column("last_studied_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sources_schema_status",
        "sources",
        ["schema_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_schema_status", table_name="sources")
    op.drop_column("sources", "last_studied_at")
    op.drop_column("sources", "drift_signal_count")
    op.drop_column("sources", "schema_status")

    op.drop_index(
        "ix_schema_study_phases_study_phase",
        table_name="schema_study_phases",
    )
    op.drop_table("schema_study_phases")

    op.drop_index("ix_schema_studies_state", table_name="schema_studies")
    op.drop_index("ix_schema_studies_source_id", table_name="schema_studies")
    op.drop_table("schema_studies")
