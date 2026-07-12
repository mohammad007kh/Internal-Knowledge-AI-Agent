"""compact activity summary column on chat_messages (004-agentic-pipeline US5 / FR-018).

Adds a single expand-only column to ``chat_messages`` so each message can
carry a *compact* activity summary that survives conversation reloads. Full
step payloads remain stream-only (SSE); only the narrated summary is
persisted here.

* ``activity_summary`` — ``JSONB``, nullable. Compact shape. Null for
  pre-feature rows and for non-agentic messages; the activity UI hides what
  is absent, so existing rows degrade gracefully.

A DB-level size guard (security review F5) caps the persisted summary at
16 KiB via ``CHECK (pg_column_size(activity_summary) <= 16384)``. Application
code additionally caps ``roles[].line`` and step labels at 200 chars and only
ever writes application-generated narration ("first 3 items + count"), never
raw row slices.

Expand-only: no existing column is dropped or destructively altered. The
model mapping for ``activity_summary`` lands with the message repo/UX slice,
not here.

Revision ID: 0037_message_activity
Revises:     0036_source_intent
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_message_activity"
down_revision: str | None = "0036_source_intent"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "ck_chat_messages_activity_summary_size"


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "activity_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "chat_messages",
        "pg_column_size(activity_summary) <= 16384",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "chat_messages", type_="check")
    op.drop_column("chat_messages", "activity_summary")
