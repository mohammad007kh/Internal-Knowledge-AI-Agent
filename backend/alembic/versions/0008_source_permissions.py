"""source_permissions table

Revision ID: 0008
Revises: 0007
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_permissions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "user_id", name="uq_source_permissions"),
    )
    op.create_index(
        "ix_source_permissions_source_id", "source_permissions", ["source_id"]
    )
    op.create_index(
        "ix_source_permissions_user_id", "source_permissions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_permissions_user_id", table_name="source_permissions")
    op.drop_index("ix_source_permissions_source_id", table_name="source_permissions")
    op.drop_table("source_permissions")
