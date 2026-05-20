"""chat: make chat_sessions.title nullable, drop server default.

U15 (lazy chat creation): the row is now inserted on the first user message
rather than on the "+ New chat" click, so the placeholder ``'New conversation'``
default has nothing to mark anymore — the column starts as NULL and the
synchronous titler step on the first turn (already implemented) fills it
with a real AI-generated title before the SSE stream resumes.

Existing rows are left untouched: any session created under the old schema
keeps its existing title.  Only the column shape changes — NOT NULL → NULL,
default ``'New conversation'`` dropped.

Revision ID: 0033
Revises:     0032
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop NOT NULL and the server default in a single DDL pass.  No rows
    # are touched — Postgres just rewrites the column metadata.
    op.execute(
        "ALTER TABLE chat_sessions "
        "ALTER COLUMN title DROP NOT NULL, "
        "ALTER COLUMN title DROP DEFAULT"
    )


def downgrade() -> None:
    # Restore the prior shape.  Existing NULL titles must be backfilled
    # before re-applying NOT NULL or the upgrade will fail.
    op.execute(
        "UPDATE chat_sessions SET title = 'New conversation' "
        "WHERE title IS NULL"
    )
    op.execute(
        "ALTER TABLE chat_sessions "
        "ALTER COLUMN title SET DEFAULT 'New conversation', "
        "ALTER COLUMN title SET NOT NULL"
    )
