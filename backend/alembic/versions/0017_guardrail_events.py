"""Create guardrail_events table.

Revision ID: 0017
Revises:     0016
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guardrail_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("blocked", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("triggered_policy_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_guardrail_events_session_id", "guardrail_events", ["session_id"])
    op.create_index("ix_guardrail_events_blocked", "guardrail_events", ["blocked"])


def downgrade() -> None:
    op.drop_index("ix_guardrail_events_blocked", "guardrail_events")
    op.drop_index("ix_guardrail_events_session_id", "guardrail_events")
    op.drop_table("guardrail_events")
