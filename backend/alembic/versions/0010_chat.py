"""Add chat_sessions and chat_messages tables.

# NOTE: op.create_table() with sa.Enum fires _on_table_create via Base.metadata
# when env.py loads chat models that register messagerole.  We bypass SQLAlchemy's
# type-event system entirely by using raw SQL DDL throughout.

Revision ID: 0010
Revises:     0009
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the native PostgreSQL ENUM type (raw DDL — bypasses _on_table_create).
    op.execute(
        "CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system')"
    )

    # 2. Create chat_sessions table via raw DDL.
    op.execute(
        """
        CREATE TABLE chat_sessions (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID        NOT NULL
                            REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT        NOT NULL DEFAULT 'New conversation',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_deleted  BOOLEAN     NOT NULL DEFAULT false
        )
        """
    )

    # 3. Create indexes on chat_sessions.
    op.execute(
        "CREATE INDEX ix_chat_sessions_user_id    ON chat_sessions (user_id)"
    )
    op.execute(
        "CREATE INDEX ix_chat_sessions_is_deleted ON chat_sessions (is_deleted)"
    )

    # 4. Create chat_messages table via raw DDL (role column uses the messagerole type).
    op.execute(
        """
        CREATE TABLE chat_messages (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id  UUID        NOT NULL
                            REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role        messagerole NOT NULL,
            content     TEXT        NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # 5. Create indexes on chat_messages.
    op.execute(
        "CREATE INDEX ix_chat_messages_session_id ON chat_messages (session_id)"
    )
    op.execute(
        "CREATE INDEX ix_chat_messages_created_at ON chat_messages (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_created_at")
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_session_id")
    op.drop_table("chat_messages")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_is_deleted")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_id")
    op.drop_table("chat_sessions")
    op.execute("DROP TYPE IF EXISTS messagerole")
