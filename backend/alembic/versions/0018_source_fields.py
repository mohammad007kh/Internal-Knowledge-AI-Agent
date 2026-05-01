"""source_fields

Revision ID: 0018
Revises:     0017
Create Date: 2026-04-22
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_mode", sa.String(), nullable=False, server_default="snapshot"))
    op.add_column("sources", sa.Column("retrieval_mode", sa.String(), nullable=False, server_default="vector_only"))
    op.add_column("sources", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("sync_mode", sa.String(), nullable=False, server_default="manual"))
    op.add_column("sources", sa.Column("sync_schedule", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("sources", sa.Column("citations_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("sources", sa.Column("file_storage_path", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("next_sync_due_at", sa.TIMESTAMP(timezone=True), nullable=True))

    # Partial index for efficient scheduled-sync polling
    op.execute(
        "CREATE INDEX ix_sources_sync_poll ON sources(sync_mode, next_sync_due_at) "
        "WHERE sync_mode = 'scheduled' AND status NOT IN ('ingesting', 'paused')"
    )
    op.create_index("ix_sources_status", "sources", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sources_status", table_name="sources")
    op.execute("DROP INDEX IF EXISTS ix_sources_sync_poll")
    for col in (
        "next_sync_due_at",
        "file_storage_path",
        "citations_enabled",
        "status",
        "last_synced_at",
        "sync_schedule",
        "sync_mode",
        "description",
        "retrieval_mode",
        "source_mode",
    ):
        op.drop_column("sources", col)
