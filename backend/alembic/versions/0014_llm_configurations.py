"""Create llm_configurations table.

Stores per-slot LLM provider configuration allowing different models and
parameters to be used for different pipeline stages.

Revision ID: 0014
Revises:     0013
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slot_name", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column(
            "temperature",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.7"),
        ),
        sa.Column(
            "max_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2048"),
        ),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
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
    )
    op.create_index(
        "ix_llm_configurations_slot_name",
        "llm_configurations",
        ["slot_name"],
        unique=True,
    )
    op.create_index(
        "ix_llm_configurations_source_id",
        "llm_configurations",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_configurations_source_id", table_name="llm_configurations")
    op.drop_index("ix_llm_configurations_slot_name", table_name="llm_configurations")
    op.drop_table("llm_configurations")
