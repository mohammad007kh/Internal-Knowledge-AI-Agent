"""Add deleted_at to sources for soft-delete; repurpose is_active = "approved/available".

After this revision:

* ``sources.deleted_at`` (TIMESTAMP WITH TIME ZONE, NULL) — soft-delete marker.
  ``deleted_at IS NULL`` means the row is not soft-deleted. List queries that
  used to filter ``is_active = TRUE`` for "exists" should now filter
  ``deleted_at IS NULL``.
* ``sources.is_active`` keeps its existing column shape and DB-level
  ``DEFAULT TRUE`` so backfilled rows stay approved (no churn). The
  default-FALSE-for-new-rows behaviour is enforced at the ORM level so freshly
  created rows via the API land as ``is_active = FALSE`` (pending admin
  approval).
* ``ix_sources_deleted_at`` — index on ``deleted_at`` to support the
  ``WHERE deleted_at IS NULL`` filter that fires on every list query.

Revision ID: 0025
Revises:     0024
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sources_deleted_at",
        "sources",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_deleted_at", table_name="sources")
    op.drop_column("sources", "deleted_at")
