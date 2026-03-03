---
id: T-014
title: Alembic Migration Workflow â€” Naming Convention, Generator Script, and Upgrade-on-Startup
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-003, T-013]
blocks: [T-020, T-040, T-060, T-080]
---

## Goal

Establish a disciplined Alembic migration workflow: enforce unique migration IDs, add a `make migrate-gen` shortcut (**T-006**), ensure `alembic upgrade head` runs automatically as part of the backend container startup sequence, and document the naming convention so all future migration files are consistent.

---

## Acceptance Criteria

- [ ] `backend/alembic.ini` sets `file_template = %%(year)d%%(month)02d%%(day)02d_%%(hour)02d%%(minute)02d_%%(rev)s_%%(slug)s`
- [ ] `backend/alembic/env.py` imports every model module before `Base.metadata` is referenced
- [ ] Backend `Dockerfile` runs `alembic upgrade head` before starting uvicorn (with `&&`)
- [ ] `make migrate` (from T-006) works inside the running container
- [ ] `alembic upgrade head` is idempotent â€” running it twice does not error
- [ ] A comment in `env.py` explicitly documents how to add a new model to autogenerate

---

## Files to Update

| Path | Change |
|------|--------|
| `backend/alembic.ini` | Set `file_template`, set `sqlalchemy.url = ${DATABASE_URL}` |
| `backend/alembic/env.py` | Import all model packages; add async migration support |
| `backend/Dockerfile` | Add `alembic upgrade head` before `CMD` |
| `backend/alembic/script.py.mako` | Improve template with FR traceability comment |

---

## Implementation

### `backend/alembic.ini` key settings

```ini
[alembic]
script_location = alembic
# File naming: YYYYMMDD_HHMM_<rev>_<slug>.py
file_template = %%(year)d%%(month)02d%%(day)02d_%%(hour)02d%%(minute)02d_%%(rev)s_%%(slug)s
sqlalchemy.url = ${DATABASE_URL}
```

### `backend/alembic/env.py` pattern

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from src.models.base import Base

# â”€â”€â”€ IMPORTANT: Import ALL model modules here so their tables
# â”€â”€â”€ are visible to Base.metadata for autogenerate.
import src.models.refresh_token      # T-012
import src.models.user               # T-020
import src.models.invitation         # T-020
import src.models.source             # T-040
import src.models.document_chunk     # T-040
import src.models.sync_job           # T-040
import src.models.chat_session       # T-060
import src.models.chat_message       # T-060
import src.models.user_source_access # T-060
import src.models.company_policy     # T-080
import src.models.guardrail_event    # T-080
import src.models.llm_configuration  # T-080

target_metadata = Base.metadata

def run_migrations_online() -> None:
    from src.core.config import settings
    connectable = create_async_engine(settings.DATABASE_URL)

    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(
                lambda sync_conn: context.configure(connection=sync_conn, target_metadata=target_metadata)
            )
            async with context.begin_transaction():
                await connection.run_sync(lambda _: context.run_migrations())

    asyncio.run(do_run())

run_migrations_online()
```

### `backend/Dockerfile` (relevant lines)

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[dev]"
COPY . .

# Run migrations then start server
CMD alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### `backend/alembic/script.py.mako` â€” migration template

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

FRs covered: <list FR IDs or 'foundation'>
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

---

## Naming Convention (for future contributors)

All migration filenames follow `YYYYMMDD_HHMM_<rev>_<slug>.py`.  
The `slug` is generated from `-m "..."` argument to `alembic revision`.  
Use imperative present tense: `add_user_table`, `enable_pgvector`, `add_guardrail_events_index`.  
Every migration file MUST list its covered FRs in the docstring (see template above).

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] `alembic upgrade head` idempotent on test DB
- [ ] `alembic downgrade base && alembic upgrade head` roundtrip succeeds
- [ ] Backend Dockerfile starts uvicorn only after successful migration
- [ ] Linter passed
