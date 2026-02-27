"""Add password_reset_tokens table and update refresh token column.

Two schema changes for T-025 (Auth Service):

1. **user_refresh_tokens** — rename ``token`` → ``token_hash`` and widen
   the column from ``String(36)`` (UUID-4) to ``String(64)`` (SHA-256 hex
   digest).

2. **password_reset_tokens** — new table that stores hashed password-reset
   tokens.  Each token is tied to a user via a CASCADE foreign key.

Revision ID: 0004
Revises:     0003
Create Date: 2026-02-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers — used by Alembic to chain migrations.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Alter refresh-token column and create password_reset_tokens table."""

    # -- user_refresh_tokens: rename + widen column --------------------------
    op.alter_column(
        "user_refresh_tokens",
        "token",
        new_column_name="token_hash",
        type_=sa.String(64),
        existing_type=sa.String(36),
        existing_nullable=False,
    )
    # Rename the unique index to match the new column name.
    op.drop_index(
        "ix_user_refresh_tokens_token",
        table_name="user_refresh_tokens",
    )
    op.create_index(
        "ix_user_refresh_tokens_token_hash",
        "user_refresh_tokens",
        ["token_hash"],
        unique=True,
    )

    # -- password_reset_tokens -----------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop password_reset_tokens and revert refresh-token column."""

    # -- password_reset_tokens -----------------------------------------------
    op.drop_index(
        "ix_password_reset_tokens_user_id",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_token_hash",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")

    # -- user_refresh_tokens: revert column name + type ----------------------
    op.drop_index(
        "ix_user_refresh_tokens_token_hash",
        table_name="user_refresh_tokens",
    )
    op.create_index(
        "ix_user_refresh_tokens_token",
        "user_refresh_tokens",
        ["token"],
        unique=True,
    )
    op.alter_column(
        "user_refresh_tokens",
        "token_hash",
        new_column_name="token",
        type_=sa.String(36),
        existing_type=sa.String(64),
        existing_nullable=False,
    )
