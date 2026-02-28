"""Business logic for source-level access control (FR-019)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, NotFoundError
from src.models.user import UserRole
from src.repositories.source_permission_repository import SourcePermissionRepository
from src.repositories.source_repository import SourceRepository
from src.repositories.user_repository import UserRepository

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

    async def grant(self, source_id: uuid.UUID, user_id: uuid.UUID) -> None:
        source = await self._source_repo.get_by_id(source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found.")
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found.")
        try:
            await self._perm_repo.create(source_id=source_id, user_id=user_id)
        except IntegrityError:
            raise ConflictError(
                f"User {user_id} already has access to source {source_id}."
            )
        logger.info(
            "source_permission.granted source_id=%s user_id=%s", source_id, user_id
        )

    async def revoke(self, source_id: uuid.UUID, user_id: uuid.UUID) -> None:
        deleted = await self._perm_repo.delete(source_id=source_id, user_id=user_id)
        if not deleted:
            raise NotFoundError(
                f"No permission found for user {user_id} on source {source_id}."
            )
        logger.info(
            "source_permission.revoked source_id=%s user_id=%s", source_id, user_id
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        return await self._perm_repo.list_source_ids_for_user(user_id)

    async def list_for_source(self, source_id: uuid.UUID) -> list[uuid.UUID]:
        return await self._perm_repo.list_user_ids_for_source(source_id)

    async def check_access(
        self,
        source_id: uuid.UUID,
        user_id: uuid.UUID,
        user_role: UserRole,
    ) -> bool:
        if user_role == UserRole.admin:
            return True
        perm = await self._perm_repo.get_by_source_and_user(
            source_id=source_id, user_id=user_id
        )
        return perm is not None
