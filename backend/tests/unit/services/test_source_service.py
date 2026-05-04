"""Unit tests for SourceService — T-090."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import NotFoundError
from src.services.source_service import SourceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source_service(source_repo):
    settings = MagicMock()
    settings.ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # valid 32-byte Fernet key (44-char URL-safe base64)
    connector_factory = MagicMock()
    return SourceService(
        source_repo=source_repo,
        settings=settings,
        connector_factory=connector_factory,
    )


def _make_source(source_id=None, owner_id=None, is_active=True):
    s = MagicMock()
    s.id = source_id or uuid.uuid4()
    s.owner_id = owner_id or uuid.uuid4()
    s.is_active = is_active
    return s


# ---------------------------------------------------------------------------
# TestListSources
# ---------------------------------------------------------------------------

class TestListSources:
    async def test_owner_sees_own_sources(self, fake_user, mock_source_repo):
        """list_sources_for_owner returns sources owned by the user."""
        own_source = _make_source(owner_id=fake_user.id)
        mock_source_repo.list_by_owner_with_jobs = AsyncMock(return_value=[own_source])
        mock_source_repo.count_by_owner = AsyncMock(return_value=1)

        service = _make_source_service(mock_source_repo)

        result = await service.list_sources_for_owner(owner_id=fake_user.id)

        assert result[0] == [own_source]
        assert result[1] == 1

    async def test_admin_can_list_all_active(self, fake_admin, mock_source_repo):
        """list_all_active_sources returns all active sources for admin."""
        sources = [_make_source(), _make_source()]
        mock_source_repo.list_active_with_jobs = AsyncMock(return_value=sources)
        mock_source_repo.count_active = AsyncMock(return_value=2)

        service = _make_source_service(mock_source_repo)

        result = await service.list_all_active_sources()

        assert result[0] == sources
        assert result[1] == 2

    async def test_empty_list_returns_empty(self, fake_user, mock_source_repo):
        """No sources → empty list."""
        mock_source_repo.list_by_owner_with_jobs = AsyncMock(return_value=[])
        mock_source_repo.count_by_owner = AsyncMock(return_value=0)

        service = _make_source_service(mock_source_repo)

        result = await service.list_sources_for_owner(owner_id=fake_user.id)

        assert result[0] == []
        assert result[1] == 0


# ---------------------------------------------------------------------------
# TestGetSource
# ---------------------------------------------------------------------------

class TestGetSource:
    async def test_valid_id_returns_source(self, mock_source_repo):
        """get_source returns Source for valid id."""
        source = _make_source()
        mock_source_repo.get_by_id = AsyncMock(return_value=source)

        service = _make_source_service(mock_source_repo)

        result = await service.get_source(source_id=source.id)

        assert result is source

    async def test_unknown_id_raises_not_found(self, mock_source_repo):
        """Unknown source id → NotFoundError."""
        mock_source_repo.get_by_id = AsyncMock(return_value=None)

        service = _make_source_service(mock_source_repo)

        with pytest.raises(NotFoundError):
            await service.get_source(source_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# TestSoftDelete
# ---------------------------------------------------------------------------

class TestSoftDelete:
    async def test_delete_source_calls_repo_soft_delete(self, mock_source_repo):
        """delete_source soft-deletes the source via the repository."""
        source = _make_source()
        mock_source_repo.get_by_id = AsyncMock(return_value=source)
        mock_source_repo.soft_delete = AsyncMock(return_value=source)

        service = _make_source_service(mock_source_repo)

        await service.delete_source(source_id=source.id)

        mock_source_repo.soft_delete.assert_called_once_with(source.id)

    async def test_delete_nonexistent_source_raises_not_found(self, mock_source_repo):
        """Deleting unknown source id → NotFoundError."""
        mock_source_repo.soft_delete = AsyncMock(return_value=None)

        service = _make_source_service(mock_source_repo)

        with pytest.raises(NotFoundError):
            await service.delete_source(source_id=uuid.uuid4())
