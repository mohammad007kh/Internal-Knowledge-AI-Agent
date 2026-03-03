"""add source_ids to chat_sessions

# NOTE: op.add_column() with a plain Python string server_default causes
# SQLAlchemy to double-quote the literal, producing invalid JSON syntax
# under asyncpg.  We bypass this by using raw DDL via op.execute().

Revision ID: 0011
Revises: 0010
Create Date: 2025-01-15 15:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_sessions"
        " ADD COLUMN source_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS source_ids")
