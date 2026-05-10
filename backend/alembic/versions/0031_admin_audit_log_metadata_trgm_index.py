"""admin_audit_log: pg_trgm GIN index on metadata::text for ILIKE search.

The audit-log viewer (``GET /api/v1/admin/audit-log``) supports a free-text
``search`` filter that does:

    cast(admin_audit_log.metadata as text) ILIKE '%needle%'

Without an index, Postgres falls back to a sequential scan over the entire
``admin_audit_log`` table.  This migration adds a ``gin_trgm_ops`` index on
the cast expression so the planner can use a trigram index for substring
matches — turning O(n) into O(log n) for typical haystack sizes.

Note on lock behaviour: ``CREATE INDEX`` (without ``CONCURRENTLY``) takes
an ``AccessExclusiveLock`` on the table, which BLOCKS WRITES for the
duration of the build.  ``admin_audit_log`` is small + write-light, so this
is acceptable here.  If we ever need to re-create this index on a hot
table, switch to ``CREATE INDEX CONCURRENTLY`` (cannot run inside a txn —
must use ``op.execute()`` with autocommit).

Revision ID: 0031
Revises:     0030
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm provides the gin_trgm_ops operator class used below.  Idempotent
    # so this migration is safe to re-apply on environments where another
    # migration already enabled the extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_audit_log_metadata_trgm "
        "ON admin_audit_log "
        "USING gin (cast(metadata as text) gin_trgm_ops)"
    )
    # Backfill prefixed action names for historical rows so the new audit-log
    # viewer's filter dropdown matches every row from before the rename.
    # Discriminator: resource_type is the canonical fact, the bare action
    # ("create", "update", "delete", "test") only ever existed pre-rename.
    op.execute(
        """
        UPDATE admin_audit_log
           SET action = resource_type || '.' || action
         WHERE resource_type IN ('ai_model', 'embedder', 'llm_setting')
           AND action IN ('create', 'update', 'delete', 'test')
        """
    )


def downgrade() -> None:
    # Reverse the backfill (strip the prefix on the affected resource_types)
    # so a downgrade leaves the table consistent with the pre-rename code.
    op.execute(
        """
        UPDATE admin_audit_log
           SET action = split_part(action, '.', 2)
         WHERE resource_type IN ('ai_model', 'embedder', 'llm_setting')
           AND action LIKE '%.%'
        """
    )
    # Drop only the index — ``pg_trgm`` may be in use by other features
    # (search ranking elsewhere), so leave the extension installed.
    op.execute("DROP INDEX IF EXISTS idx_admin_audit_log_metadata_trgm")
