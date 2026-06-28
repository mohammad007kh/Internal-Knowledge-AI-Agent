"""connection-failure metadata on schema_studies (retry-then-officially-fail).

Adds two expand-only nullable columns so a failed schema study can record WHY
the database connection failed and how many attempts the retry seam made:

* ``failure_category`` — ``VARCHAR(32)``, nullable. A closed
  ``DBConnFailureCategory`` token (e.g. ``AUTH_FAILED``, ``DB_UNREACHABLE``).
* ``attempts_made`` — ``INTEGER``, nullable. The honest number of connect
  attempts (1 for a fail-fast permanent failure; up to the policy budget for a
  transient one).

Populated together or both NULL — set only when the failure is a DB *connection*
failure surfaced by ``connect_with_retry``. NULL for pre-feature rows, for
non-connection failures (e.g. SAMPLING), and for user cancellations.

Expand-only: nullable adds with no default → metadata-only on PostgreSQL 11+,
no table rewrite, no backfill, no long lock. Existing rows degrade gracefully
(the admin UI treats NULL as "not applicable").

Revision ID: 0038_schema_study_failure_meta
Revises:     0037_message_activity
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0038_schema_study_failure_meta"
down_revision: str | None = "0037_message_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schema_studies",
        sa.Column("failure_category", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "schema_studies",
        sa.Column("attempts_made", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # Reverse order of add.
    op.drop_column("schema_studies", "attempts_made")
    op.drop_column("schema_studies", "failure_category")
