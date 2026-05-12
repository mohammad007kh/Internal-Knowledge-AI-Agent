"""analytics: add created_at indexes for the /admin/analytics daily GROUP BYs.

The redesigned ``/api/v1/analytics`` surface runs daily
``GROUP BY date_trunc('day', created_at)`` aggregations over ``sync_jobs``
and counts ``admin_audit_log`` rows since midnight.  Neither table had an
index on ``created_at``:

* ``sync_jobs`` — ``status`` is indexed (added in 0009) but ``created_at``
  is not, so the daily sync-activity chart was a sequential scan.
* ``admin_audit_log`` — ``resource_type`` / ``admin_user_id`` / ``resource_id``
  are indexed (0017-era) but ``created_at`` is not; the audit-log viewer
  ordering and the "privileged actions today" KPI both filter/sort on it.

``chat_messages.created_at`` already has an index (declared ``index=True`` on
the model since 0010 / `0020_chat_message_fields`), so no index is added for
it here.

Lock behaviour: plain ``CREATE INDEX`` (not ``CONCURRENTLY``) takes an
``AccessExclusiveLock`` on the table for the build, blocking writes.  Both
tables are small and write-light, so this is acceptable — if either becomes
hot, switch to ``CREATE INDEX CONCURRENTLY`` (must run outside a txn).

Revision ID: 0032
Revises:     0031
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_sync_jobs_created_at",
        "sync_jobs",
        ["created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_admin_audit_log_created_at",
        "admin_audit_log",
        ["created_at"],
        if_not_exists=True,
    )
    # Composite indexes for the "latest row per source" lookups:
    #   * /api/v1/analytics/needs-attention does
    #     `DISTINCT ON (source_id) ... ORDER BY source_id, created_at DESC`
    #     over sync_jobs;
    #   * SourceRepository.get_study_summary_bundle does a per-source
    #     `schema_studies ORDER BY started_at DESC LIMIT 5`.
    # Without these Postgres resolves them with a full sort; the composites
    # let it do an index range scan keyed on source_id.
    op.create_index(
        "ix_sync_jobs_source_id_created_at",
        "sync_jobs",
        ["source_id", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_schema_studies_source_id_started_at",
        "schema_studies",
        ["source_id", "started_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_schema_studies_source_id_started_at",
        table_name="schema_studies",
        if_exists=True,
    )
    op.drop_index(
        "ix_sync_jobs_source_id_created_at", table_name="sync_jobs", if_exists=True
    )
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log", if_exists=True)
    op.drop_index("ix_sync_jobs_created_at", table_name="sync_jobs", if_exists=True)
