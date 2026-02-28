"""Create sources table.

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the PostgreSQL enum type explicitly so it exists before the table.
    sourcetype_enum = postgresql.ENUM(
        "web_url",
        "file_upload",
        "database",
        "confluence",
        "sharepoint",
        name="sourcetype",
    )
    sourcetype_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "web_url",
                "file_upload",
                "database",
                "confluence",
                "sharepoint",
                name="sourcetype",
                create_type=False,  # already created above
            ),
            nullable=False,
        ),
        sa.Column("config_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index("ix_sources_name", "sources", ["name"])
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_sources_owner_id", table_name="sources")
    op.drop_index("ix_sources_name", table_name="sources")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS sourcetype")
