"""sources.next_sync_due_at -> TIMESTAMPTZ (FX22).

Idempotent guard for the scheduled-sync TZ regression.

Migration 0018 already created ``next_sync_due_at`` as ``TIMESTAMP WITH TIME
ZONE``, so on every standard deployment this is a no-op. The fix that actually
makes scheduled syncs work in FX22 is the model column type change in
``src/models/source.py`` (``DateTime(timezone=True)``), which corrects the
SQLAlchemy bind-parameter cast asyncpg was rejecting.

This migration exists so any environment that was manually altered (or any
future schema-drift situation that flipped the column to naive ``TIMESTAMP``)
is brought back in line with the model. ``ALTER COLUMN ... TYPE TIMESTAMPTZ
USING column AT TIME ZONE 'UTC'`` is a no-op when the column is already
TIMESTAMPTZ and, when the column is naive, interprets the stored values as
UTC — the convention the rest of the codebase uses.

Revision ID: 0035
Revises:     0034
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent guard. ``ALTER COLUMN ... TYPE TIMESTAMPTZ`` with a
    # ``USING ... AT TIME ZONE 'UTC'`` clause behaves correctly when the
    # column is already TIMESTAMPTZ ONLY if the session time zone is UTC —
    # otherwise the AT-TIME-ZONE round-trip can shift values. To stay safe
    # under arbitrary session TZ settings, inspect the column type first
    # and only convert when the column is genuinely naive. Using
    # ``information_schema.columns.data_type`` keeps this portable across
    # PostgreSQL versions.
    op.execute(
        """
        DO $do$
        DECLARE
            current_type text;
        BEGIN
            SELECT data_type INTO current_type
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'sources'
               AND column_name = 'next_sync_due_at';

            IF current_type = 'timestamp without time zone' THEN
                EXECUTE 'ALTER TABLE sources '
                        'ALTER COLUMN next_sync_due_at TYPE TIMESTAMPTZ '
                        'USING next_sync_due_at AT TIME ZONE ''UTC''';
            END IF;
            -- Already TIMESTAMP WITH TIME ZONE (the migration-0018 shape) -> no-op.
        END
        $do$;
        """
    )


def downgrade() -> None:
    # Revert to naive timestamp, interpreting the stored UTC instants as
    # wall-clock values. Mirrors the upgrade's guard so re-running on a
    # column that is already naive is a no-op. Production should never
    # need this — the cron task only works against the TIMESTAMPTZ shape.
    op.execute(
        """
        DO $do$
        DECLARE
            current_type text;
        BEGIN
            SELECT data_type INTO current_type
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'sources'
               AND column_name = 'next_sync_due_at';

            IF current_type = 'timestamp with time zone' THEN
                EXECUTE 'ALTER TABLE sources '
                        'ALTER COLUMN next_sync_due_at TYPE TIMESTAMP WITHOUT TIME ZONE '
                        'USING next_sync_due_at AT TIME ZONE ''UTC''';
            END IF;
        END
        $do$;
        """
    )
