"""user_citations_preference

Adds show_citations_preference to users table.
(full_name already exists from initial table creation.)

Revision ID: 0019
Revises:     0018
Create Date: 2026-04-22
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "show_citations_preference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "show_citations_preference")
