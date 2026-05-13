"""sync_jobs: add 'cancelled' status + cancelled_at column (U16).

Cooperative cancellation introduces a fifth terminal state for a SyncJob run.
A task that observes the Redis cancel flag at a safe checkpoint flips its row
to ``status='cancelled'``, stamps ``cancelled_at=now()``, and exits. Work
completed before the checkpoint is retained.

Existing rows are untouched — the value is only ever written by code that
reaches a cancellation checkpoint AFTER this migration runs.

Revision ID: 0034
Revises:     0033
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Append 'cancelled' to the existing native enum. ALTER TYPE ... ADD
    #    VALUE cannot run inside a transaction block when the enum is also
    #    being used in the same transaction — we run it standalone using
    #    autocommit-friendly DDL. The `IF NOT EXISTS` guard makes the
    #    migration safe to re-apply.
    op.execute("ALTER TYPE syncstatus ADD VALUE IF NOT EXISTS 'cancelled'")

    # 2) Add the cancelled_at column. Nullable — only populated when the
    #    cancellation checkpoint fires.
    op.execute(
        "ALTER TABLE sync_jobs "
        "ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    # Drop the column. We deliberately do NOT remove 'cancelled' from the
    # enum — PostgreSQL has no DROP VALUE for enums, and any rows that
    # acquired this status would corrupt under a partial downgrade. Leave
    # the value in place; it is harmless when no code path writes it.
    op.execute("ALTER TABLE sync_jobs DROP COLUMN IF EXISTS cancelled_at")
