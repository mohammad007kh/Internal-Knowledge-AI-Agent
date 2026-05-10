"""add_chat_message_feedback_columns

Adds ``feedback_rating`` (+1 / -1 / NULL) and ``feedback_comment`` (text) to
the ``chat_messages`` table so the existing FeedbackButtons UI on the
assistant-message bubble can persist thumbs-up / thumbs-down + an optional
comment.

The frontend has been calling
``POST /api/v1/chat/sessions/{session_id}/messages/{message_id}/feedback``
since `5a2e884` (the inline-bubble-meta-row feature), but the endpoint
never existed server-side and the columns weren't there to back it. The
mutation silently failed in production with a "Failed to save feedback"
toast. This migration + the new endpoint close the gap.

Revision ID: 0029
Revises:     0028
Create Date: 2026-05-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("feedback_rating", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("feedback_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "feedback_comment")
    op.drop_column("chat_messages", "feedback_rating")
