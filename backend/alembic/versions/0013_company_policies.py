"""Create company_policies table.

Stores admin-defined natural-language policy rules evaluated by the
guardrail layer before and after LLM generation.

Revision ID: 0013
Revises:     0012
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        "ix_company_policies_created_by",
        "company_policies",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_company_policies_is_active",
        "company_policies",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_company_policies_is_active", table_name="company_policies")
    op.drop_index("ix_company_policies_created_by", table_name="company_policies")
    op.drop_table("company_policies")
