"""Add sync_jobs table and syncstatus enum.

Implements T-060: SyncJob ORM Model.

Revision ID: 0009
Revises:     0008
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────── #

revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None


# ── helpers ───────────────────────────────────────────────────────────────── #

syncstatus_enum = sa.Enum(
    "pending",
    "running",
    "success",
    "failed",
    name="syncstatus",
)


# ── upgrade ───────────────────────────────────────────────────────────────── #


def upgrade() -> None:
    # 1. Create the native PostgreSQL ENUM type first.
    syncstatus_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create the sync_jobs table.
    op.create_table(
        "sync_jobs",
        sa.Column(
            "id",
            sa.String(length=36),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "success",
                "failed",
                name="syncstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "finished_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "documents_synced",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "chunks_created",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3. Create indexes.
    op.create_index(
        "ix_sync_jobs_source_id",
        "sync_jobs",
        ["source_id"],
    )
    op.create_index(
        "ix_sync_jobs_status",
        "sync_jobs",
        ["status"],
    )

    # 4. Attach the auto-update trigger for updated_at.
    op.execute(
        """
        CREATE TRIGGER sync_jobs_updated_at
        BEFORE UPDATE ON sync_jobs
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """
    )


# ── downgrade ─────────────────────────────────────────────────────────────── #


def downgrade() -> None:
    op.drop_index("ix_sync_jobs_status", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_source_id", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    syncstatus_enum.drop(op.get_bind(), checkfirst=True)
