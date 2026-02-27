"""Create user_refresh_tokens table.

Stores opaque UUID-4 refresh tokens used by the rotating-refresh-token
authentication strategy.  Each token is tied to a user via a CASCADE
foreign key so that deleting or deactivating a user automatically removes
all their outstanding refresh tokens.

Revision ID: 0002
Revises:     0001
Create Date: 2026-02-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers — used by Alembic to chain migrations.
revision: str = "0002"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``user_refresh_tokens`` table and its indexes."""
    op.create_table(
        "user_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Unique constraint + index on token for fast look-ups during validation.
    op.create_index(
        "ix_user_refresh_tokens_token",
        "user_refresh_tokens",
        ["token"],
        unique=True,
    )
    # Non-unique index on user_id to speed up bulk revocation queries.
    op.create_index(
        "ix_user_refresh_tokens_user_id",
        "user_refresh_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ``user_refresh_tokens`` table and its indexes."""
    op.drop_index("ix_user_refresh_tokens_user_id", table_name="user_refresh_tokens")
    op.drop_index("ix_user_refresh_tokens_token", table_name="user_refresh_tokens")
    op.drop_table("user_refresh_tokens")
