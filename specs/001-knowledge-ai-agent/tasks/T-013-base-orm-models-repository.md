---
id: T-013
title: Base ORM Models â€” TimestampMixin, SoftDeleteMixin, UUIDMixin, and Common Patterns
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-003]
blocks: [T-020, T-040, T-060, T-080]
---

## Goal

Define the canonical SQLAlchemy 2.x base model mixins and patterns that every ORM model in the project inherits. Establish the `Base` declarative class, `UUIDMixin`, `TimestampMixin`, and `SoftDeleteMixin`. Include a `BaseRepository` ABC that all repositories extend.

> **Note**: This task refines what was scaffolded in T-003 (`base.py`). The repository pattern is new.

---

## Acceptance Criteria

- [ ] All ORM models use `UUID(as_uuid=True)` primary keys defaulting to `uuid.uuid4`
- [ ] All tables have `created_at TIMESTAMPTZ` and `updated_at TIMESTAMPTZ` (auto-updated on write)
- [ ] Soft-deletable models have `deleted_at TIMESTAMPTZ NULL`; `SoftDeleteMixin.is_deleted` property returns bool
- [ ] `BaseRepository[T]` provides `get_by_id`, `list`, `create`, `update`, `soft_delete`, `hard_delete`
- [ ] All repos in scope use `AsyncSession` exclusively â€” no sync queries
- [ ] Unit tests verify `created_at` and `updated_at` are set on insert

---

## Files to Create / Update

| Path | Status |
|------|--------|
| `backend/src/models/base.py` | **Update** (extend T-003 stub) |
| `backend/src/repositories/base_repository.py` | Create |
| `backend/tests/unit/test_base_models.py` | Create |

---

## Implementation

### `backend/src/models/base.py` (full content)

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    def to_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
```

### `backend/src/repositories/base_repository.py`

```python
from __future__ import annotations
import uuid
from typing import Generic, TypeVar, Type, Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.base import Base, SoftDeleteMixin

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    async def get_by_id(self, id_: uuid.UUID, include_deleted: bool = False) -> T | None:
        stmt = select(self._model).where(self._model.id == id_)
        if not include_deleted and issubclass(self._model, SoftDeleteMixin):
            stmt = stmt.where(self._model.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        stmt = select(self._model).limit(limit).offset(offset)
        if issubclass(self._model, SoftDeleteMixin):
            stmt = stmt.where(self._model.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(self, **kwargs) -> T:
        obj = self._model(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        await self._session.refresh(obj)
        return obj

    async def update(self, id_: uuid.UUID, **kwargs) -> T | None:
        stmt = (
            update(self._model)
            .where(self._model.id == id_)
            .values(**kwargs)
            .returning(self._model)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, id_: uuid.UUID) -> bool:
        from datetime import datetime, timezone
        obj = await self.get_by_id(id_)
        if obj and isinstance(obj, SoftDeleteMixin):
            obj.soft_delete()
            await self._session.flush()
            return True
        return False

    async def hard_delete(self, id_: uuid.UUID) -> bool:
        obj = await self.get_by_id(id_, include_deleted=True)
        if obj:
            await self._session.delete(obj)
            await self._session.flush()
            return True
        return False
```

---

## Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Database | PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns |
| Migrations | Alembic versioned |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Testing | pytest + httpx Â· â‰¥80% coverage |

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] Unit tests pass
- [ ] Linter passed
- [ ] All downstream models import from `src.models.base`
