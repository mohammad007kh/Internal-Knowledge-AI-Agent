# T-077 â€” Chat Session Repository Service + Source Permission Integration

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
FR-019: source access per user per source â€” NEVER expose unapproved data
PostgreSQL 16 Â· UUID PKs Â· soft-delete
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
1. Implement `ChatSessionService` â€” thin service layer over the repositories
   that enforces FR-019: resolves the user's permitted `source_ids` when
   `body.source_ids` is empty  
2. Patch the `send_message` endpoint in T-076 to use `ChatSessionService`
   instead of directly passing `body.source_ids`  
3. Ensure `ChatSession` stores an optional `source_ids: list[str]` JSON column
   so sessions remember which sources were selected at creation time  

---

## Acceptance Criteria

- [ ] `ChatSession.source_ids` JSONB column present in ORM and migration
- [ ] Migration `0010_chat_source_ids.py` creates the column safely with `ALTER TABLE`
- [ ] `ChatSessionService.get_source_ids_for_session()` returns permitted source IDs for a user
- [ ] If session `source_ids` is non-empty, those are used (user pre-selected)
- [ ] If session `source_ids` is empty, falls back to `SourcePermissionService.get_permitted_source_ids(user_id)`
- [ ] `POST /chat/sessions/{id}/messages` never exposes sources the user has no permission to

---

## 1  `alembic/versions/0010_chat_source_ids.py`

```python
"""add source_ids to chat_sessions

Revision ID: 00000000000010
Revises: 00000000000009
Create Date: 2025-01-15 15:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "00000000000010"
down_revision = "00000000000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "source_ids",
            JSONB,
            nullable=False,
            server_default="'[]'::jsonb",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "source_ids")
```

---

## 2  `app/models/chat.py` â€” patch (add `source_ids` column)

```python
# Inside ChatSession class, after the `title` column:

from sqlalchemy.dialects.postgresql import JSONB as _JSONB

source_ids: Mapped[list] = mapped_column(
    _JSONB,
    nullable=False,
    default=list,
    server_default="'[]'::jsonb",
)
```

---

## 3  `app/services/chat_session_service.py`

```python
# app/services/chat_session_service.py
"""ChatSessionService â€” session lifecycle and FR-019 source resolution."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.repositories.chat_repository import ChatSessionRepository
from app.services.source_permission_service import SourcePermissionService

logger = logging.getLogger(__name__)


class ChatSessionService:
    """High-level operations on chat sessions.

    Responsibilities:
    - Create sessions with optional source pre-selection
    - Resolve the effective source_ids for a pipeline run (FR-019)
    - Soft-delete sessions owned by the requesting user
    """

    def __init__(
        self,
        chat_session_repository: ChatSessionRepository,
        source_permission_service: SourcePermissionService,
    ) -> None:
        self._repo = chat_session_repository
        self._perms = source_permission_service

    # â”€â”€ Session lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def create_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        title: str = "New conversation",
        source_ids: list[str] | None = None,
    ) -> ChatSession:
        """Create and persist a new chat session.

        If ``source_ids`` is provided, validate that the user actually has
        access to each one before storing them.
        """
        permitted: list[str] = []
        if source_ids:
            permitted = await self._perms.filter_permitted(
                db, user_id=user_id, candidate_ids=source_ids
            )
        session = await self._repo.create(db, user_id=user_id, title=title)
        session.source_ids = permitted
        await db.flush()
        return session

    # â”€â”€ FR-019 source resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def get_source_ids_for_session(
        self,
        db: AsyncSession,
        *,
        session: ChatSession,
        user_id: str,
        override_ids: list[str] | None = None,
    ) -> list[str]:
        """Return the effective list of source UUIDs for a pipeline run.

        Priority:
        1. ``override_ids`` (from request body) filtered to permitted only
        2. ``session.source_ids`` if pre-configured at session creation
        3. All sources the user currently has permission to access

        Never returns IDs that the user is not permitted to see.
        """
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

    # â”€â”€ Ownership enforcement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def get_owned_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> Optional[ChatSession]:
        """Return session only if it exists, is not deleted, and owner matches."""
        session = await self._repo.get(db, session_id=session_id)
        if session is None or session.user_id != user_id:
            return None
        return session
```

---

## 4  `app/services/source_permission_service.py` â€” patch

Add `filter_permitted` helper method:

```python
# Append to SourcePermissionService class:

async def filter_permitted(
    self,
    db: AsyncSession,
    *,
    user_id: str,
    candidate_ids: list[str],
) -> list[str]:
    """Return only the IDs from ``candidate_ids`` the user may access."""
    if not candidate_ids:
        return []
    permitted_set = set(
        await self.get_permitted_source_ids(db, user_id=user_id)
    )
    return [sid for sid in candidate_ids if sid in permitted_set]
```

---

## 5  `containers.py` â€” patch

```python
# Add after langfuse_tracing_service:

from app.services.chat_session_service import ChatSessionService

chat_session_service = providers.Factory(
    ChatSessionService,
    chat_session_repository=chat_session_repository,
    source_permission_service=source_permission_service,
)
```

---

## 6  `app/api/v1/chat.py` â€” patch (use `ChatSessionService`)

In the `send_message` endpoint, replace:

```python
# OLD:
source_ids = body.source_ids or []  # TODO: fall back to user's permitted sources

# NEW (after injecting chat_session_service via Depends):
source_ids = await chat_session_service.get_source_ids_for_session(
    db_session,
    session=session,
    user_id=str(current_user.id),
    override_ids=body.source_ids or None,
)
```

Also update the `create_session` endpoint to use `ChatSessionService.create_session()`:

```python
# OLD:
session = await chat_session_repository.create(...)
await db_session.commit()

# NEW:
session = await chat_session_service.create_session(
    db_session,
    user_id=str(current_user.id),
    title=body.title,
    source_ids=body.source_ids or None,
)
await db_session.commit()
```

---

## 7  Unit Tests â€” `tests/unit/services/test_chat_session_service.py`

```python
# tests/unit/services/test_chat_session_service.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.chat_session_service import ChatSessionService


@pytest.fixture()
def service():
    mock_repo = AsyncMock()
    mock_perm = AsyncMock()
    return ChatSessionService(
        chat_session_repository=mock_repo,
        source_permission_service=mock_perm,
    ), mock_repo, mock_perm


@pytest.mark.asyncio
async def test_get_source_ids_uses_override(service):
    svc, _, mock_perm = service
    mock_perm.filter_permitted.return_value = ["src-1"]
    mock_session = MagicMock()
    mock_session.source_ids = []

    result = await svc.get_source_ids_for_session(
        AsyncMock(),
        session=mock_session,
        user_id="user-1",
        override_ids=["src-1", "src-99"],
    )
    assert result == ["src-1"]
    mock_perm.filter_permitted.assert_called_once()


@pytest.mark.asyncio
async def test_get_source_ids_falls_back_to_all_permitted(service):
    svc, _, mock_perm = service
    mock_perm.get_permitted_source_ids.return_value = ["src-a", "src-b"]
    mock_session = MagicMock()
    mock_session.source_ids = []

    result = await svc.get_source_ids_for_session(
        AsyncMock(),
        session=mock_session,
        user_id="user-1",
        override_ids=None,
    )
    assert result == ["src-a", "src-b"]
    mock_perm.get_permitted_source_ids.assert_called_once_with(
        pytest.ANY, user_id="user-1"
    )


@pytest.mark.asyncio
async def test_get_owned_session_returns_none_for_wrong_user(service):
    svc, mock_repo, _ = service
    mock_session = MagicMock()
    mock_session.user_id = "other-user"
    mock_repo.get.return_value = mock_session

    result = await svc.get_owned_session(
        AsyncMock(), session_id="sess-1", user_id="user-1"
    )
    assert result is None
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `alembic/versions/0010_chat_source_ids.py` |
| PATCH  | `app/models/chat.py` |
| CREATE | `app/services/chat_session_service.py` |
| PATCH  | `app/services/source_permission_service.py` |
| PATCH  | `containers.py` |
| PATCH  | `app/api/v1/chat.py` |
| CREATE | `tests/unit/services/test_chat_session_service.py` |
