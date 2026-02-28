"""Expand invitations.token column from VARCHAR(36) to VARCHAR(64).

The token is generated with secrets.token_urlsafe() which produces ~43-char
strings, exceeding the original VARCHAR(36) constraint.

Revision ID: 0005
Revises:     0004
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "invitations",
        "token",
        existing_type=sa.String(36),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "invitations",
        "token",
        existing_type=sa.String(64),
        type_=sa.String(36),
        existing_nullable=False,
    )
