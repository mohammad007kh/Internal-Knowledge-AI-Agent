---
id: T-003
title: PostgreSQL + pgvector Init, Alembic Baseline Migration, and DB Healthcheck
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
---

## ðŸ“‹ Embedded Context (READ THIS FIRST)

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 |
| Database | PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns |
| Migrations | Alembic versioned â€” never direct DDL in production |
| Naming | snake_case tables and columns |
| Primary Keys | UUID (uuid4), not auto-increment integers |

### Domain Rules
- pgvector extension MUST be enabled via Alembic migration, not manual SQL
- All tables use UUID PKs, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`, `deleted_at TIMESTAMPTZ NULL`
- Alembic must be configured for async SQLAlchemy (asyncpg driver)
- `alembic upgrade head` MUST be idempotent (safe to run multiple times)

### Feature Summary
PostgreSQL 16 with pgvector for both relational data and vector similarity search. Alembic manages all schema changes. The baseline migration enables the pgvector extension and creates the `alembic_version` table.

### Gate Criteria
- `alembic upgrade head` completes without errors on a fresh database
- `alembic downgrade base` followed by `alembic upgrade head` succeeds (roundtrip)
- `psql -c "SELECT extname FROM pg_extension WHERE extname='vector';"` returns `vector`

---

## ðŸŽ¯ Objective

Configure SQLAlchemy async engine, set up Alembic with the correct async migration environment, enable the pgvector extension, and establish the `TimestampMixin` and `UUIDMixin` base model patterns used by all subsequent ORM models.

---

## ðŸ› ï¸ Implementation Details

### Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/core/database.py` | Async SQLAlchemy engine factory, `AsyncSession`, `get_db()` FastAPI dependency |
| `backend/src/models/base.py` | Declarative base, `TimestampMixin`, `UUIDMixin`, `SoftDeleteMixin` |
| `backend/alembic.ini` | Alembic config pointing to `DATABASE_URL` env var |
| `backend/alembic/env.py` | Async Alembic env using `AsyncEngine` + `run_migrations_online()` |
| `backend/alembic/versions/0001_enable_pgvector.py` | Enable `vector` extension |

### Files to Update
- `backend/src/core/__init__.py` â€” export `get_db`, `AsyncSession`

### Code / Logic Requirements

**`backend/src/core/database.py`:**
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from src.core.config import settings  # reads DATABASE_URL from env

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

**`backend/src/models/base.py`:**
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```

**Alembic `env.py`** must use `AsyncEngine`, import all models before `Base.metadata`, and use `asyncio.run()` pattern for async migrations.

**Migration `0001_enable_pgvector.py`:**
```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
```

---

## ðŸ”Œ Wiring Checklist

- [ ] `get_db()` dependency exported from `src.core.database`
- [ ] All model files import `Base` from `src.models.base`
- [ ] `alembic.ini` references `DATABASE_URL` (not hardcoded credentials)
- [ ] `alembic/env.py` imports `Base.metadata` from `src.models.base`
- [ ] `backend/Dockerfile` runs `alembic upgrade head` before starting uvicorn

---

## âœ… Verification

```bash
# Run migrations on clean database
cd backend
alembic upgrade head
echo "Exit code: $?"  # Must be 0

# Verify pgvector extension is enabled
psql ${DATABASE_URL} -c "SELECT extname FROM pg_extension WHERE extname='vector';" | grep -q vector && echo "pgvector OK"

# Verify alembic_version table exists
psql ${DATABASE_URL} -c "\dt alembic_version" | grep -q "alembic_version" && echo "Alembic table OK"

# Verify roundtrip
alembic downgrade base
alembic upgrade head
echo "Roundtrip: OK"
```

**Success Criteria:**
- `alembic upgrade head` exits with code 0
- `pg_extension` table contains `vector`
- `alembic downgrade base` then `upgrade head` succeeds without errors
- `TimestampMixin`, `UUIDMixin`, `SoftDeleteMixin` importable from `src.models.base`

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
