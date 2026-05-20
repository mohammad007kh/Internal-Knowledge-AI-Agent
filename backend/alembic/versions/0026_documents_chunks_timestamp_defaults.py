"""Add server_default=now() to documents/chunks created_at + updated_at.

Bug fix: migration 0007 declared ``created_at`` / ``updated_at`` as
``DateTime(timezone=True), nullable=False`` but with NO ``server_default``.
The ORM model uses :class:`src.models.base.TimestampMixin` which DOES
declare ``server_default=func.now()``, so on INSERT SQLAlchemy omits the
column expecting the DB to populate it — which fails with
``NotNullViolationError`` because the DB has no default.

The Source table (migration 0006) already has ``server_default=now()``
on these columns, which is why source inserts work but document/chunk
inserts blow up during ``tasks.sync_source``.

This revision aligns documents/chunks with the established pattern.

Revision ID: 0026
Revises:     0025
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("documents", "chunks"):
        op.alter_column(
            table,
            "created_at",
            server_default=sa.text("now()"),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "updated_at",
            server_default=sa.text("now()"),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in ("documents", "chunks"):
        op.alter_column(
            table,
            "created_at",
            server_default=None,
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "updated_at",
            server_default=None,
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
