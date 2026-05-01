"""chat_message_fields

Adds sources_cited (JSONB), message_type, is_partial to chat_messages.

Revision ID: 0020
Revises:     0019
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "sources_cited",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "message_type",
            sa.String(),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "is_partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "is_partial")
    op.drop_column("chat_messages", "message_type")
    op.drop_column("chat_messages", "sources_cited")
