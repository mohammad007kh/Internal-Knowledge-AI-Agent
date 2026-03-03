"""Create system_health_events table.

Revision ID: 0012
Revises: 0011
Create Date: 2025-01-15 17:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE system_health_events (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            component_name   VARCHAR(120) NOT NULL,
            event_type       VARCHAR(32)  NOT NULL,
            attempt_number   INTEGER      NOT NULL DEFAULT 0,
            error_detail     TEXT,
            timestamp        TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_system_health_events_id"
        " ON system_health_events (id)"
    )
    op.execute(
        "CREATE INDEX ix_system_health_events_component_name"
        " ON system_health_events (component_name)"
    )
    op.execute(
        "CREATE INDEX ix_system_health_events_event_type"
        " ON system_health_events (event_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_health_events")
