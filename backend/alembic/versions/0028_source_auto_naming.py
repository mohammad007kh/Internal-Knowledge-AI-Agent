"""add_source_auto_naming_columns

Adds the AI auto-naming bookkeeping columns to the ``sources`` table:

* ``name_status``         — user_set | pending_ai | ai_set  (NOT NULL,
                            default user_set so existing rows are untouched)
* ``description_status``  — same domain
* ``auto_name_and_description`` — captures the user's checkbox at creation
                                  time so a future explicit Regenerate can
                                  honour the original intent.

These three columns drive the new auto-naming pipeline (Feature F1-F12) and
the "Naming…" shimmer in the admin sources table.

Revision ID: 0028
Revises:     0027
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # name_status / description_status — short string columns. Backfill all
    # existing rows to "user_set" so legacy sources never accidentally get
    # picked up by the auto-naming worker.
    op.add_column(
        "sources",
        sa.Column(
            "name_status",
            sa.String(length=16),
            nullable=False,
            server_default="user_set",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "description_status",
            sa.String(length=16),
            nullable=False,
            server_default="user_set",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "auto_name_and_description",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Helpful index for the worker query "find me sources still pending AI".
    # Partial index keeps it tiny — most sources are user_set.
    op.create_index(
        "ix_sources_name_status_pending_ai",
        "sources",
        ["name_status"],
        postgresql_where=sa.text("name_status = 'pending_ai'"),
    )


def downgrade() -> None:
    op.drop_index("ix_sources_name_status_pending_ai", table_name="sources")
    op.drop_column("sources", "auto_name_and_description")
    op.drop_column("sources", "description_status")
    op.drop_column("sources", "name_status")
