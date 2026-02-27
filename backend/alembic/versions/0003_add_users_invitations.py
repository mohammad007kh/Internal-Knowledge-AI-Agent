"""Create users and invitations tables.

Adds the core identity tables required by T-021.  The ``users`` table stores
application accounts (with soft-delete via ``deleted_at``). The ``invitations``
table tracks sign-up invitations sent by administrators.

A ``userrole`` PostgreSQL enum is created first so that both tables can
reference it for the ``role`` column.

Revision ID: 0003
Revises:     0002
Create Date: 2026-02-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers — used by Alembic to chain migrations.
revision: str = "0003"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

# Enum type shared by both tables.
userrole_enum = postgresql.ENUM("admin", "user", name="userrole", create_type=False)


def upgrade() -> None:
    """Create the ``userrole`` enum, ``users`` table, and ``invitations`` table."""

    # -- enum ----------------------------------------------------------------
    userrole_enum.create(op.get_bind(), checkfirst=True)

    # -- users ---------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(60), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "role",
            userrole_enum,
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # -- invitations ---------------------------------------------------------
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "role",
            userrole_enum,
            nullable=False,
            server_default="user",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_invitations_email", "invitations", ["email"], unique=False)
    op.create_index("ix_invitations_token", "invitations", ["token"], unique=True)


def downgrade() -> None:
    """Drop ``invitations``, ``users``, and ``userrole`` enum."""
    op.drop_index("ix_invitations_token", table_name="invitations")
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_table("invitations")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    userrole_enum.drop(op.get_bind(), checkfirst=True)
