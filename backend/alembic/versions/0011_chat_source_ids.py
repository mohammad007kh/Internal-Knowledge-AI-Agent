"""add source_ids to chat_sessions

Revision ID: 0011
Revises: 0010
Create Date: 2025-01-15 15:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "source_ids",
            JSONB,
            nullable=False,
            server_default="'[]'::jsonb",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "source_ids")
