"""add_source_connection_health_columns_and_align_db_retrieval_mode

Adds three columns to ``sources`` so the system can track per-source
connection health independently of the admin-approval flag (``is_active``):

* ``connection_status`` — one of ``healthy | degraded | failed | unknown``,
  defaulting to ``unknown``. Updated by :class:`SyncJobService` (sync runs)
  and :class:`SourceService.test_connection` (manual probes). The chat
  source picker hides ``failed`` rows so unreachable sources do not silently
  return empty answers.
* ``connection_last_checked_at`` — UTC timestamp of the most recent probe
  (sync run or test-connection click). Powers the "Last tested 4 min ago"
  microcopy on the admin sources detail page.
* ``connection_last_error`` — most recent failure message, truncated
  server-side to 500 chars and never carrying connection strings or
  credentials. Surfaced inline as a tooltip on the failed row.

Existing rows are backfilled to ``connection_status='unknown'`` (the
default) so the new column is non-null from day one.

This migration ALSO performs a one-time alignment of ``retrieval_mode``
for every persisted ``database`` source:

    UPDATE sources
       SET retrieval_mode = 'text_to_query'
     WHERE source_type = 'database' AND retrieval_mode != 'text_to_query';

Rationale (irreversible by design): pre-existing DB rows whose
``retrieval_mode`` was ``vector_only`` or ``hybrid`` could never actually
be queried — the agent's :mod:`source_router` shells DB sources straight
into the text-to-query branch and ignores the column for embedding paths.
The persisted state therefore lied. This UPDATE aligns the row with what
the agent code already does at runtime so the admin UI and the actual
behaviour stop disagreeing.

Revision ID: 0030
Revises:     0029
Create Date: 2026-05-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. New connection-health columns on sources
    # ------------------------------------------------------------------
    op.add_column(
        "sources",
        sa.Column(
            "connection_status",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "connection_last_checked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "connection_last_error",
            sa.String(length=500),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sources_connection_status",
        "sources",
        ["connection_status"],
    )

    # ------------------------------------------------------------------
    # 2. Force every persisted DB source onto retrieval_mode='text_to_query'
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "UPDATE sources "
            "SET retrieval_mode = 'text_to_query' "
            "WHERE source_type = 'database' "
            "AND retrieval_mode != 'text_to_query'"
        )
    )


def downgrade() -> None:
    # The retrieval_mode UPDATE is intentionally irreversible — there is no
    # way to know which DB rows were originally vector_only vs hybrid, and
    # the answer "neither, because the agent always treated them as
    # text_to_query" is the correct one.
    op.drop_index("ix_sources_connection_status", table_name="sources")
    op.drop_column("sources", "connection_last_error")
    op.drop_column("sources", "connection_last_checked_at")
    op.drop_column("sources", "connection_status")
