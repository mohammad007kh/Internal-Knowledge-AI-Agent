"""Unit tests for ChatSessionService (T-077)."""
from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from src.services.chat_session_service import ChatSessionService


@pytest.fixture()
def service():
    mock_repo = AsyncMock()
    mock_perm = AsyncMock()
    svc = ChatSessionService(
        chat_session_repository=mock_repo,
        source_permission_service=mock_perm,
    )
    return svc, mock_repo, mock_perm


@pytest.mark.asyncio
async def test_get_source_ids_uses_override(service):
    svc, _, mock_perm = service
    mock_perm.filter_permitted.return_value = ["src-1"]
    mock_session = MagicMock()
    mock_session.source_ids = []
    result = await svc.get_source_ids_for_session(
        AsyncMock(), session=mock_session, user_id="user-1", override_ids=["src-1", "src-99"]
    )
    assert result == ["src-1"]
    mock_perm.filter_permitted.assert_called_once()


@pytest.mark.asyncio
async def test_get_source_ids_falls_back_to_session_ids(service):
    svc, _, mock_perm = service
    mock_perm.filter_permitted.return_value = ["src-a"]
    mock_session = MagicMock()
    mock_session.source_ids = ["src-a", "src-b"]
    result = await svc.get_source_ids_for_session(
        AsyncMock(), session=mock_session, user_id="user-1", override_ids=None
    )
    assert result == ["src-a"]
    mock_perm.filter_permitted.assert_called_once()


@pytest.mark.asyncio
async def test_get_source_ids_falls_back_to_all_permitted(service):
    svc, _, mock_perm = service
    mock_perm.get_permitted_source_ids.return_value = ["src-a", "src-b"]
    mock_session = MagicMock()
    mock_session.source_ids = []
    result = await svc.get_source_ids_for_session(
        AsyncMock(), session=mock_session, user_id="user-1", override_ids=None
    )
    assert result == ["src-a", "src-b"]
    mock_perm.get_permitted_source_ids.assert_called_once_with(ANY, user_id="user-1")


@pytest.mark.asyncio
async def test_get_owned_session_returns_none_for_wrong_user(service):
    svc, mock_repo, _ = service
    mock_session = MagicMock()
    mock_session.user_id = "other-user"
    mock_repo.get.return_value = mock_session
    result = await svc.get_owned_session(AsyncMock(), session_id="00000000-0000-0000-0000-000000000001", user_id="user-1")
    assert result is None


@pytest.mark.asyncio
async def test_get_owned_session_returns_session_for_correct_user(service):
    svc, mock_repo, _ = service
    mock_session = MagicMock()
    mock_session.user_id = "user-1"
    mock_repo.get.return_value = mock_session
    result = await svc.get_owned_session(AsyncMock(), session_id="00000000-0000-0000-0000-000000000001", user_id="user-1")
    assert result is mock_session
