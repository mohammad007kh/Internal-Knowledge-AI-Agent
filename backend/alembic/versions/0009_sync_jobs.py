"""Add sync_jobs table and syncstatus enum.

# NOTE: op.create_table() with sa.Enum fires _on_table_create via Base.metadata
# because env.py loads source.py → sync_job.py registering the model table.
# We bypass SQLAlchemy's type-event system by using raw SQL DDL throughout.

Implements T-060: SyncJob ORM Model.

Revision ID: 0009
Revises:     0008
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────── #

revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None


# ── upgrade ───────────────────────────────────────────────────────────────── #


def upgrade() -> None:
    # Use raw SQL DDL to bypass SQLAlchemy's _on_table_create event system.
    # When env.py imports source.py → sync_job.py, the SyncJob model registers
    # its Table (including the Enum column) in Base.metadata.  If we use
    # op.create_table() SQLAlchemy fires before_create on that metadata Table,
    # which triggers _on_table_create on the model's Enum even though it has
    # create_type=False — a known interaction between Python-enum-backed
    # sa.Enum types and the metadata event dispatch.  Raw DDL is immune.

    # 1. Create the native PostgreSQL ENUM type (idempotent).
    op.execute(
        "CREATE TYPE syncstatus AS ENUM ('pending', 'running', 'success', 'failed')"
    )

    # 2. Create the sync_jobs table via raw DDL.
    op.execute(
        """
        CREATE TABLE sync_jobs (
            id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id    UUID          NOT NULL
                             REFERENCES sources(id) ON DELETE CASCADE,
            status       syncstatus    NOT NULL DEFAULT 'pending',
            started_at   TIMESTAMPTZ,
            finished_at  TIMESTAMPTZ,
            error_message TEXT,
            documents_synced INTEGER   NOT NULL DEFAULT 0,
            chunks_created   INTEGER   NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )

    # 3. Create indexes.
    op.execute("CREATE INDEX ix_sync_jobs_source_id ON sync_jobs (source_id)")
    op.execute("CREATE INDEX ix_sync_jobs_status    ON sync_jobs (status)")

    # 4. Create the generic updated_at trigger helper (idempotent).
    #    This function was never explicitly created in an earlier migration;
    #    0009 is the first migration to use a BEFORE UPDATE trigger, so we
    #    define it here with CREATE OR REPLACE so subsequent runs are no-ops.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 5. Attach the auto-update trigger for updated_at.
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
    op.execute("DROP TYPE IF EXISTS syncstatus")
