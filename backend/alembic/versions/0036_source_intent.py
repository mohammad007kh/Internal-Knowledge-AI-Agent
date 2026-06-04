"""source intent metadata columns (004-agentic-pipeline US1 / FR-001).

Adds six expand-only columns to ``sources`` so each source can carry its
own retrieval intent, governed by a tri-state capability ramp
(``pending_ai -> ai_set -> user_set``):

* ``purpose`` — admin-authored business purpose (1-2 sentences). AI never
  writes this field (FR-002: admin supplies purpose).
* ``example_questions`` — ``list[str]`` of ~3 sample questions; AI-proposed
  after study, admin-editable.
* ``out_of_scope`` — ``list[str]`` of topics this source cannot answer;
  AI-proposed, admin-editable.
* ``cross_source_hints`` — optional ``list[{topic, source_id}]`` "for X see
  source Y" redirects. v1: admin-authored only.
* ``intent_status`` — one status for the whole intent bundle
  (``pending_ai | ai_set | user_set``); NOT NULL, defaults to
  ``pending_ai`` so existing rows degrade gracefully everywhere.
* ``intent_updated_at`` — UTC timestamp stamped on any intent write
  (AI or admin).

Expand-only: no existing column is dropped or destructively altered.
Existing rows are backfilled to ``intent_status='pending_ai'`` via the
server default. An index on ``intent_status`` supports the capability-ramp
filters. The model mapping (``src/models/source.py``) lands in T-020.

Revision ID: 0036_source_intent
Revises:     0035
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036_source_intent"
down_revision: str | None = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "purpose",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "example_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "out_of_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "cross_source_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "intent_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending_ai",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "intent_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sources_intent_status",
        "sources",
        ["intent_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_intent_status", table_name="sources")
    op.drop_column("sources", "intent_updated_at")
    op.drop_column("sources", "intent_status")
    op.drop_column("sources", "cross_source_hints")
    op.drop_column("sources", "out_of_scope")
    op.drop_column("sources", "example_questions")
    op.drop_column("sources", "purpose")
