# T-054 â€” SourcePermission Repository & Service

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x (async) Â· dependency-injector
PostgreSQL 16 Â· UUID PKs
FR-019: source access is per-user per-source
RBAC: admin role auto-passes access checks
```

## Goal
Provide a repository and service layer that manage the `source_permissions` table.
The service is the SINGLE authority on "can user X see source Y?"  The retrieval
pipeline calls `check_access` before embedding search; no code elsewhere should
bypass this.

---

## File 1 â€” `app/repositories/source_permission_repository.py`

```python
"""CRUD helpers for the source_permissions table."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source_permission import SourcePermission


class SourcePermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_source_and_user(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> SourcePermission | None:
        stmt = select(SourcePermission).where(
            SourcePermission.source_id == source_id,
            SourcePermission.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_ids_for_source(
        self, source_id: uuid.UUID
    ) -> list[uuid.UUID]:
        stmt = select(SourcePermission.user_id).where(
            SourcePermission.source_id == source_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_source_ids_for_user(
        self, user_id: uuid.UUID
    ) -> list[uuid.UUID]:
        stmt = select(SourcePermission.source_id).where(
            SourcePermission.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> SourcePermission:
        """Raises IntegrityError on duplicate; caller converts to 409."""
        perm = SourcePermission(source_id=source_id, user_id=user_id)
        self._session.add(perm)
        await self._session.flush()
        await self._session.refresh(perm)
        return perm

    async def delete(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Return True if a row was deleted, False if not found."""
        stmt = (
            delete(SourcePermission)
            .where(
                SourcePermission.source_id == source_id,
                SourcePermission.user_id == user_id,
            )
            .returning(SourcePermission.id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.fetchone() is not None
```

---

## File 2 â€” `app/services/source_permission_service.py`

```python
"""Business logic for source-level access control (FR-019)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictException, NotFoundException
from app.models.user import UserRole
from app.repositories.source_permission_repository import (
    SourcePermissionRepository,
)
from app.repositories.source_repository import SourceRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class SourcePermissionService:
    def __init__(
        self,
        source_permission_repo: SourcePermissionRepository,
        source_repo: SourceRepository,
        user_repo: UserRepository,
    ) -> None:
        self._perm_repo = source_permission_repo
        self._source_repo = source_repo
        self._user_repo = user_repo

    # ------------------------------------------------------------------
    # Grant
    # ------------------------------------------------------------------
    async def grant(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """
        Grant user_id access to source_id.
        Raises:
            NotFoundException: source or user not found.
            ConflictException: permission already exists.
        """
        source = await self._source_repo.get_by_id(source_id)
        if source is None:
            raise NotFoundException(f"Source {source_id} not found.")

        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundException(f"User {user_id} not found.")

        try:
            await self._perm_repo.create(source_id=source_id, user_id=user_id)
        except IntegrityError:
            raise ConflictException(
                f"User {user_id} already has access to source {source_id}."
            )
        logger.info(
            "source_permission.granted source_id=%s user_id=%s",
            source_id,
            user_id,
        )

    # ------------------------------------------------------------------
    # Revoke
    # ------------------------------------------------------------------
    async def revoke(
        self, source_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """
        Revoke user_id access to source_id.
        Raises:
            NotFoundException: permission row not found.
        """
        deleted = await self._perm_repo.delete(
            source_id=source_id, user_id=user_id
        )
        if not deleted:
            raise NotFoundException(
                f"No permission found for user {user_id} on source {source_id}."
            )
        logger.info(
            "source_permission.revoked source_id=%s user_id=%s",
            source_id,
            user_id,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def list_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Return all source IDs the user has been explicitly granted."""
        return await self._perm_repo.list_source_ids_for_user(user_id)

    async def list_for_source(self, source_id: uuid.UUID) -> list[uuid.UUID]:
        """Return all user IDs that have access to a source."""
        return await self._perm_repo.list_user_ids_for_source(source_id)

    async def check_access(
        self,
        source_id: uuid.UUID,
        user_id: uuid.UUID,
        user_role: UserRole,
    ) -> bool:
        """
        Return True if the user may read chunks from source_id.

        Rules:
        - Admin role â†’ always True (FR-019 admin bypass).
        - Otherwise â†’ must have a row in source_permissions.
        """
        if user_role == UserRole.ADMIN:
            return True
        perm = await self._perm_repo.get_by_source_and_user(
            source_id=source_id, user_id=user_id
        )
        return perm is not None
```

---

## File 3 â€” `app/containers.py` (patch)

```python
# After existing repository providers, add:
source_permission_repository: providers.Factory = providers.Factory(
    SourcePermissionRepository,
    session=db_session,
)

# After source_service provider:
source_permission_service: providers.Factory = providers.Factory(
    SourcePermissionService,
    source_permission_repo=source_permission_repository,
    source_repo=source_repository,
    user_repo=user_repository,
)
```

---

## Acceptance Criteria

1. `SourcePermissionRepository.create` raises `IntegrityError` on duplicate FK pair.
2. `SourcePermissionRepository.delete` returns `False` when no row deleted.
3. `grant()` raises `NotFoundException` for missing source or user.
4. `grant()` raises `ConflictException` on duplicate (wraps `IntegrityError`).
5. `revoke()` raises `NotFoundException` when no row deleted.
6. `check_access()` returns `True` for `UserRole.ADMIN` without touching DB.
7. `check_access()` returns `True` only when a matching row exists for non-admin.
8. Both provider entries are present in `app/containers.py`.
