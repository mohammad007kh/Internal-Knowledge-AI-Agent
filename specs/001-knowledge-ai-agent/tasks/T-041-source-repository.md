# T-041 — Source Repository

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x async · dependency-injector
PostgreSQL 16 · UUID PKs · soft-delete pattern
```

## Goal
Implement `SourceRepository` extending `BaseRepository[Source]` with all data-access methods needed by `SourceService`.

---

## File — `app/repositories/source_repository.py`

```python
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    """Data-access layer for Source entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Source)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Source]:
        """Return all sources owned by the given user (active + inactive)."""
        stmt = (
            select(Source)
            .where(Source.owner_id == owner_id)
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Source]:
        """Return all active sources (admin view)."""
        stmt = (
            select(Source)
            .where(Source.is_active == True)  # noqa: E712
            .order_by(Source.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        """Count sources owned by a user (for pagination totals)."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Source)
            .where(Source.owner_id == owner_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_active(self) -> int:
        """Count all active sources."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Source)
            .where(Source.is_active == True)  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def find_by_name_and_owner(
        self,
        name: str,
        owner_id: uuid.UUID,
    ) -> Source | None:
        """Look up a source by unique (name, owner_id) pair."""
        stmt = select(Source).where(
            Source.name == name,
            Source.owner_id == owner_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, source_id: uuid.UUID) -> Source | None:
        """Fetch a single source by PK regardless of active status."""
        stmt = select(Source).where(Source.id == source_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    async def deactivate(self, source_id: uuid.UUID) -> bool:
        """
        Soft-delete: sets is_active=False.
        Returns True if a row was updated, False if not found.
        """
        stmt = (
            update(Source)
            .where(Source.id == source_id, Source.is_active == True)  # noqa: E712
            .values(is_active=False)
            .returning(Source.id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def list_by_ids(self, source_ids: list[uuid.UUID]) -> list[Source]:
        """Bulk fetch by list of PKs (used by permission service)."""
        if not source_ids:
            return []
        stmt = select(Source).where(Source.id.in_(source_ids), Source.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
```

---

## Integration Notes

- `BaseRepository[T]` provides: `save(entity)`, `delete(entity)`, `flush()`, `refresh(entity)` — do NOT re-implement those here
- `deactivate()` uses `UPDATE ... RETURNING` to detect missing rows in a single round-trip
- `list_by_ids` is used by `SourcePermissionService` to materialise permission lists (T-054)

---

## Acceptance Criteria

- [ ] `SourceRepository` is importable from `app.repositories.source_repository`
- [ ] `find_by_name_and_owner` returns `None` when no match (not raises)
- [ ] `deactivate` returns `False` for a non-existent or already-inactive source
- [ ] All queries use SQLAlchemy 2.x `select()` style (no legacy `session.query()`)
- [ ] DI container in T-037 wires `SourceRepository` as a `Factory` provider
