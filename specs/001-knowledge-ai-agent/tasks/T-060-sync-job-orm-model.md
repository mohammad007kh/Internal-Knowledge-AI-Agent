# T-060 â€” SyncJob ORM Model & Migration

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
PostgreSQL 16 + pgvector Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
Celery + Redis Â· Beat replicas=1 STRICT
RFC 7807 Problem Details â€” all non-2xx API responses
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

## Goal
Define the `SyncJob` SQLAlchemy ORM model, add `SyncStatus` enum, and create the
Alembic migration `0008_sync_jobs`.  The model tracks the lifecycle of every
connector fetch run: PENDING â†’ RUNNING â†’ SUCCESS | FAILED.

---

## Acceptance Criteria

- [ ] `SyncStatus` enum has exactly four values: PENDING, RUNNING, SUCCESS, FAILED
- [ ] `SyncJob` has all required columns (id, source_id FK, status, started_at, finished_at, error_message, documents_synced, chunks_created, created_at, updated_at)
- [ ] `source_id` FK references `sources.id` with CASCADE DELETE
- [ ] `status` column stored as PostgreSQL native ENUM type (not VARCHAR)
- [ ] Migration 0008 chains from `0007_source_permissions`
- [ ] `SyncJob` imported in `app/models/__init__.py`
- [ ] containers.py reflects no changes needed here (model registration is implicit via Base metadata)

---

## 1  Enum â€” `app/models/enums.py`

**Patch** â€” add `SyncStatus` alongside any existing enums:

```python
# app/models/enums.py
import enum


class SourceType(str, enum.Enum):
    """Supported connector types."""
    WEB_URL = "web_url"
    FILE_UPLOAD = "file_upload"
    DATABASE = "database"
    CONFLUENCE = "confluence"
    SHAREPOINT = "sharepoint"


class SyncStatus(str, enum.Enum):
    """Lifecycle states for a SyncJob run."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED  = "failed"
```

*Note:* `str` mixin ensures JSON serialisation works without custom encoder.

---

## 2  ORM Model â€” `app/models/sync_job.py`

```python
# app/models/sync_job.py
"""SyncJob â€” tracks a single connector ingestion run."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import orm

from app.db.base import Base
from app.models.enums import SyncStatus
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.source import Source


class SyncJob(UUIDMixin, TimestampMixin, Base):
    """One row per connector sync attempt."""

    __tablename__ = "sync_jobs"

    # ------------------------------------------------------------------ FK
    source_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        sa.ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -------------------------------------------------------------- Status
    status: orm.Mapped[SyncStatus] = orm.mapped_column(
        sa.Enum(
            SyncStatus,
            name="syncstatus",
            create_type=False,  # created by migration
        ),
        nullable=False,
        default=SyncStatus.PENDING,
        server_default=sa.text("'pending'"),
    )

    # -------------------------------------------------------------- Timing
    started_at: orm.Mapped[datetime | None] = orm.mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
        default=None,
    )
    finished_at: orm.Mapped[datetime | None] = orm.mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
        default=None,
    )

    # -------------------------------------------------------------- Detail
    error_message: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    documents_synced: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    chunks_created: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )

    # ---------------------------------------------------------- Relationship
    source: orm.Mapped["Source"] = orm.relationship(
        "Source",
        back_populates="sync_jobs",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SyncJob id={self.id} source_id={self.source_id} "
            f"status={self.status.value}>"
        )
```

---

## 3  Patch `app/models/source.py` â€” add `sync_jobs` back-ref

```python
# Inside class Source â€” add after existing relationships:

    sync_jobs: orm.Mapped[list["SyncJob"]] = orm.relationship(
        "SyncJob",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="raise",
    )
```

---

## 4  Register in `app/models/__init__.py`

```python
# app/models/__init__.py
from app.models.user import User                          # noqa: F401
from app.models.invitation import Invitation              # noqa: F401
from app.models.source import Source                      # noqa: F401
from app.models.source_permission import SourcePermission # noqa: F401
from app.models.document import Document                  # noqa: F401
from app.models.chunk import Chunk                        # noqa: F401
from app.models.sync_job import SyncJob                   # noqa: F401
from app.models.enums import SourceType, SyncStatus       # noqa: F401
```

---

## 5  Alembic Migration â€” `alembic/versions/0008_sync_jobs.py`

```python
"""0008 â€” sync_jobs table

Revision ID: 00000000000008
Revises:     00000000000007
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "00000000000008"
down_revision = "00000000000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create native ENUM type
    syncstatus = sa.Enum(
        "pending", "running", "success", "failed",
        name="syncstatus",
    )
    syncstatus.create(op.get_bind(), checkfirst=True)

    # 2. Create sync_jobs table
    op.create_table(
        "sync_jobs",
        sa.Column("id",                sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id",         sa.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status",            sa.Enum("pending", "running", "success", "failed", name="syncstatus", create_type=False), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at",        sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at",       sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message",     sa.Text,    nullable=True),
        sa.Column("documents_synced",  sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("chunks_created",    sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at",        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at",        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 3. Indexes
    op.create_index("ix_sync_jobs_source_id", "sync_jobs", ["source_id"])
    op.create_index("ix_sync_jobs_status",    "sync_jobs", ["status"])

    # 4. updated_at auto-update trigger (reuse existing helper if present)
    op.execute("""
        CREATE OR REPLACE TRIGGER sync_jobs_updated_at
        BEFORE UPDATE ON sync_jobs
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.drop_table("sync_jobs")
    sa.Enum(name="syncstatus").drop(op.get_bind(), checkfirst=True)
```

**Assumption:** `update_updated_at_column()` PL/pgSQL function was created in an
earlier migration (consistent with pattern in 0002â€“0007).

---

## 6  Verification Checklist

```bash
# Apply migration
alembic upgrade 0008

# Confirm table + enum
psql $DATABASE_URL -c "\d sync_jobs"
psql $DATABASE_URL -c "\dT syncstatus"

# Python smoke test
from app.models.sync_job import SyncJob
from app.models.enums import SyncStatus
assert SyncStatus.PENDING.value == "pending"
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-033 â€” sync job tracking | `SyncJob` rows track every run |
| FR-033 â€” status transitions | PENDINGâ†’RUNNINGâ†’SUCCESS\|FAILED columns |
| FR-033 â€” error capture | `error_message` TEXT column |
