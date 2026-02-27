"""Enable pgvector extension.

This is the baseline (initial) migration.  All subsequent migrations build
on top of this revision.

Revision ID: 0001
Revises:     (none — this is the first migration)
Create Date: 2025-07-14
"""

from alembic import op

# Revision identifiers — used by Alembic to chain migrations.
revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable the pgvector extension.

    Uses IF NOT EXISTS so re-running is always safe (idempotent).
    Must happen before any table with a VECTOR column is created.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Drop the pgvector extension.

    WARNING: This will fail if any vector columns still exist.
    Drop all vector columns / tables before downgrading past this revision.
    """
    op.execute("DROP EXTENSION IF EXISTS vector")
