# T-001: Alembic Migrations 0017–0020

| Field | Value |
|---|---|
| **Status** | Pending |
| **Created** | 2026-04-21 |
| **Feature** | 003-phase2-completion |
| **Branch** | `003-phase2-completion` |
| **User Story** | US-1, US-2, US-3, US-6 |
| **Requirements** | FR-001 (source wizard), FR-006 (file upload), FR-014 (chat streaming), FR-032 (profile) |
| **Priority** | P0 |

---

## Embedded Context

This task file is self-contained. Read only this file, `specs/003-phase2-completion/index.md`, and `specs/003-phase2-completion/traceability.md` during implementation (Context Pinning).

### Registry Standards (MUST follow)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (dependency-injector IoC) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.primary_key_type` | uuid |
| `database.migration_strategy` | versioned (Alembic) |
| `database.naming_tables` | snake_case |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python), kebab-case (Next.js) |
| `conventions.variables` | snake_case (Python) |
| `conventions.classes` | PascalCase |
| `api.versioning` | url (/api/v1/) |
| `api.error_format` | rfc7807 |
| `backend.language` | python |
| `backend.runtime_version` | python:3.12 |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `backend.job_queue` | celery + redis |
| `backend.sse_pattern` | fastapi_streaming_response |
| `testing.unit_framework` | pytest |
| `testing.integration_framework` | httpx |

### Domain Rules (MUST follow)

- All new services MUST be registered in `backend/src/core/container.py` and injected via FastAPI `Depends()`
- All database access goes through a Repository class — no raw SQL in services or routers
- Alembic migration required for every schema change — never modify models without a migration
- New backend routes protected with `get_current_user` (any auth) or `require_admin` (admin-only)
- RFC 7807 error responses: `{"detail": "...", "type": "...", "status": 400}`
- File bytes NEVER pass through FastAPI — use MinIO presigned PUT URLs
- Every LLM call wrapped with Langfuse tracing
- `connection_config` and `file_storage_path` MUST NEVER appear in API responses

### Hard Constraints

1. File bytes must NEVER pass through the FastAPI backend (MinIO presigned PUT)
2. Every LLM call MUST be Langfuse-traced (Constitution §II)
3. Celery Beat runs as a single replica — no duplicate scheduled jobs

---

## Objective

Create Alembic migrations 0017–0020 and update the corresponding SQLAlchemy models to add the schema fields required by the Phase 2 wizard, chat streaming, profile, and source description history features.

---

## Implementation Details

### Files to Create

#### 1. `backend/alembic/versions/0017_source_fields.py`

Adds 9 new columns to `sources` table plus 2 indexes.

```python
"""source_fields

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_mode", sa.String(), nullable=False, server_default="snapshot"))
    op.add_column("sources", sa.Column("retrieval_mode", sa.String(), nullable=False, server_default="vector_only"))
    op.add_column("sources", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("sync_mode", sa.String(), nullable=False, server_default="manual"))
    op.add_column("sources", sa.Column("sync_schedule", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("sources", sa.Column("citations_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("sources", sa.Column("file_storage_path", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("next_sync_due_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.execute(
        "CREATE INDEX ix_sources_sync_poll ON sources(sync_mode, next_sync_due_at) "
        "WHERE sync_mode = 'scheduled' AND status NOT IN ('ingesting', 'paused')"
    )
    op.create_index("ix_sources_status", "sources", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sources_status", table_name="sources")
    op.execute("DROP INDEX IF EXISTS ix_sources_sync_poll")
    for col in (
        "next_sync_due_at", "file_storage_path", "citations_enabled", "status",
        "last_synced_at", "sync_schedule", "sync_mode", "description",
        "retrieval_mode", "source_mode",
    ):
        op.drop_column("sources", col)
```

#### 2. `backend/alembic/versions/0018_user_fields.py`

Adds `full_name`, `show_citations_preference` to `users`.

```python
"""user_fields

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("show_citations_preference", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "show_citations_preference")
    op.drop_column("users", "full_name")
```

#### 3. `backend/alembic/versions/0019_chat_message_fields.py`

Adds `sources_cited` (JSONB), `message_type`, `is_partial` to `chat_messages`.

```python
"""chat_message_fields

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("sources_cited", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column("message_type", sa.String(), nullable=False, server_default="normal"),
    )
    op.add_column(
        "chat_messages",
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "is_partial")
    op.drop_column("chat_messages", "message_type")
    op.drop_column("chat_messages", "sources_cited")
```

#### 4. `backend/alembic/versions/0020_source_description_history.py`

Creates `source_description_history` table.

```python
"""source_description_history

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_description_history",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("replaced_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("replaced_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_source_description_history_source_id",
        "source_description_history",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_description_history_source_id", table_name="source_description_history")
    op.drop_table("source_description_history")
```

#### 5. `backend/src/models/source_description_history.py`

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.base import Base


class SourceDescriptionHistory(Base):
    __tablename__ = "source_description_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    replaced_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    replaced_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
```

### Files to Update

#### `backend/src/models/source.py`

Add the following mapped columns to the existing `Source` model:

```python
source_mode: Mapped[str] = mapped_column(String, nullable=False, default="snapshot")
retrieval_mode: Mapped[str] = mapped_column(String, nullable=False, default="vector_only")
description: Mapped[str | None] = mapped_column(Text, nullable=True)
sync_mode: Mapped[str] = mapped_column(String, nullable=False, default="manual")
sync_schedule: Mapped[str | None] = mapped_column(String, nullable=True)
last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
citations_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
file_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
next_sync_due_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

#### `backend/src/models/user.py`

Add:

```python
full_name: Mapped[str | None] = mapped_column(String, nullable=True)
show_citations_preference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

#### `backend/src/models/chat_message.py` (or equivalent path)

Add:

```python
sources_cited: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
message_type: Mapped[str] = mapped_column(String, nullable=False, default="normal")
is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

---

## Wiring Checklist (Web)

- [x] New SQLAlchemy model (`SourceDescriptionHistory`) added
- [x] Alembic migrations created (0017, 0018, 0019, 0020)
- [ ] No new services to register in container (schema-only task)
- [ ] No new API routes (schema-only task)
- [ ] No new Celery tasks
- [ ] No new frontend routes

---

## Verification Command

```bash
cd backend && python -m alembic upgrade head && python -m alembic current
```

**Expected output:** Shows current revision as `0020 (head)`, no errors.

---

## Completion Log

- [ ] Migration 0017 created and applied
- [ ] Migration 0018 created and applied
- [ ] Migration 0019 created and applied
- [ ] Migration 0020 created and applied
- [ ] `Source` model updated with 10 new fields
- [ ] `User` model updated with 2 new fields
- [ ] `ChatMessage` model updated with 3 new fields
- [ ] `SourceDescriptionHistory` model created
- [ ] `alembic upgrade head` runs cleanly
- [ ] `alembic current` returns `0020 (head)`
- [ ] `alembic downgrade -4 && alembic upgrade head` round-trip succeeds
- [ ] All registry standards respected (snake_case, UUID PKs, timezone-aware timestamps)
