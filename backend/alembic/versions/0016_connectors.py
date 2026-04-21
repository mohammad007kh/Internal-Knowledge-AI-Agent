"""Create connectors table.

Revision ID: 0016
Revises:     0015
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "connector_type",
            postgresql.ENUM(
                "web_url",
                "file_upload",
                "database",
                "confluence",
                "sharepoint",
                name="sourcetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_connectors_id", "connectors", ["id"])
    op.create_index("ix_connectors_name", "connectors", ["name"])
    op.create_index("ix_connectors_owner_id", "connectors", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_connectors_owner_id", table_name="connectors")
    op.drop_index("ix_connectors_name", table_name="connectors")
    op.drop_index("ix_connectors_id", table_name="connectors")
    op.drop_table("connectors")
