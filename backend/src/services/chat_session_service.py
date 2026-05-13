"""ChatSessionService — session lifecycle and FR-019 source resolution."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat import ChatSession
from src.repositories.chat_repository import ChatSessionRepository
from src.services.source_permission_service import SourcePermissionService

logger = logging.getLogger(__name__)


class ChatSessionService:
    def __init__(
        self,
        chat_session_repository: ChatSessionRepository,
        source_permission_service: SourcePermissionService,
    ) -> None:
        self._repo = chat_session_repository
        self._perms = source_permission_service

    async def create_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        title: str | None = None,
        source_ids: list[str] | None = None,
    ) -> ChatSession:
        permitted: list[str] = []
        if source_ids:
            permitted = await self._perms.filter_permitted(
                db, user_id=user_id, candidate_ids=source_ids
            )
        session = await self._repo.create(db, user_id=uuid.UUID(user_id), title=title)
        session.source_ids = permitted
        await db.flush()
        return session

    async def get_source_ids_for_session(
        self,
        db: AsyncSession,
        *,
        session: ChatSession,
        user_id: str,
        override_ids: list[str] | None = None,
    ) -> list[str]:
        candidate_ids: list[str] | None = override_ids or session.source_ids or None

        if candidate_ids:
            permitted = await self._perms.filter_permitted(
                db, user_id=user_id, candidate_ids=candidate_ids
            )
        else:
            permitted = await self._perms.get_permitted_source_ids(db, user_id=user_id)

        if not permitted:
            logger.warning(
                "get_source_ids_for_session: user=%s has no permitted sources",
                user_id,
            )
        return permitted

    async def get_owned_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> ChatSession | None:
        session = await self._repo.get(db, uuid.UUID(session_id))
        if session is None or str(session.user_id) != str(user_id):
            return None
        return session
