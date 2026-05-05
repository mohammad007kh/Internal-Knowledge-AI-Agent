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
# TestListWithCounts (T-107 ingestion-clarity)
# ---------------------------------------------------------------------------

class TestListWithCounts:
    """Aggregate-listing methods feed the four-stage admin sources strip."""

    async def test_admin_with_counts_forwards_to_repo(self, fake_admin, mock_source_repo):
        """list_all_sources_with_counts delegates to repo.list_with_counts (admin scope)."""
        src_a = _make_source()
        src_b = _make_source()
        rows = [(src_a, 3, 12), (src_b, 0, 0)]
        mock_source_repo.list_with_counts = AsyncMock(return_value=(rows, 2))

        service = _make_source_service(mock_source_repo)
        result = await service.list_all_sources_with_counts(skip=0, limit=50)

        assert result == (rows, 2)
        mock_source_repo.list_with_counts.assert_awaited_once_with(
            owner_id=None, skip=0, limit=50, available_only=False
        )

    async def test_owner_with_counts_passes_owner_id(self, fake_user, mock_source_repo):
        """list_sources_for_owner_with_counts forwards owner_id + available_only."""
        src = _make_source(owner_id=fake_user.id)
        mock_source_repo.list_with_counts = AsyncMock(
            return_value=([(src, 5, 17)], 1)
        )

        service = _make_source_service(mock_source_repo)
        result = await service.list_sources_for_owner_with_counts(
            owner_id=fake_user.id, skip=0, limit=20, available_only=True
        )

        assert result[1] == 1
        # Tuple shape: (source, document_count, chunk_count) — these are the
        # fields the API stitches onto SourceListItem.
        returned_src, doc_n, chunk_n = result[0][0]
        assert returned_src is src
        assert doc_n == 5
        assert chunk_n == 17
        mock_source_repo.list_with_counts.assert_awaited_once_with(
            owner_id=fake_user.id, skip=0, limit=20, available_only=True
        )

    async def test_with_counts_empty(self, fake_admin, mock_source_repo):
        """Empty repo response → empty list, total 0."""
        mock_source_repo.list_with_counts = AsyncMock(return_value=([], 0))

        service = _make_source_service(mock_source_repo)
        rows, total = await service.list_all_sources_with_counts()

        assert rows == []
        assert total == 0


# ---------------------------------------------------------------------------
# TestSourceListItemShape (T-107 — schema contract)
# ---------------------------------------------------------------------------


class TestSourceListItemShape:
    """SourceListItem must expose the 8 ingestion-clarity fields."""

    def test_schema_has_required_clarity_fields(self):
        """The pydantic schema declares the new admin-table fields."""
        from src.schemas.source import SourceListItem

        required = {
            "status",
            "last_synced_at",
            "description",
            "source_mode",
            "sync_mode",
            "document_count",
            "chunk_count",
            "has_upload",
        }
        assert required.issubset(set(SourceListItem.model_fields.keys()))

    def test_has_upload_default_false(self):
        """has_upload defaults to False when no path is set."""
        from datetime import datetime, timezone

        from src.models.enums import SourceType
        from src.schemas.source import SourceListItem

        item = SourceListItem(
            id=uuid.uuid4(),
            name="x",
            source_type=SourceType.WEB_URL,
            is_active=False,
            created_at=datetime.now(tz=timezone.utc),
        )
        assert item.has_upload is False
        assert item.document_count == 0
        assert item.chunk_count == 0

    def test_counts_round_trip(self):
        """document_count / chunk_count survive construction."""
        from datetime import datetime, timezone

        from src.models.enums import SourceType
        from src.schemas.source import SourceListItem

        item = SourceListItem(
            id=uuid.uuid4(),
            name="x",
            source_type=SourceType.FILE_UPLOAD,
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
            document_count=4,
            chunk_count=42,
            has_upload=True,
            status="ready",
            source_mode="snapshot",
            sync_mode="manual",
            description="hello",
        )
        assert item.document_count == 4
        assert item.chunk_count == 42
        assert item.has_upload is True
        assert item.status == "ready"


# ---------------------------------------------------------------------------
# TestMakeListItem (T-107 — API row builder)
# ---------------------------------------------------------------------------


class TestMakeListItem:
    """_make_list_item must stitch counts + has_upload onto the schema row.

    Uses :class:`SimpleNamespace` rather than :class:`MagicMock` because
    pydantic's ``from_attributes`` walks ``latest_job`` and friends — auto-
    generated MagicMock attributes break the UUID/datetime validators.
    """

    @staticmethod
    def _src(**overrides):
        from datetime import datetime, timezone
        from types import SimpleNamespace

        from src.models.enums import SourceType

        defaults = {
            "id": uuid.uuid4(),
            "name": "test",
            "source_type": SourceType.WEB_URL,
            "is_active": False,
            "deleted_at": None,
            "created_at": datetime.now(tz=timezone.utc),
            "sync_jobs": [],
            "status": "pending",
            "last_synced_at": None,
            "description": None,
            "source_mode": "snapshot",
            "sync_mode": "manual",
            "file_storage_path": None,
            "latest_job": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_has_upload_when_file_storage_path_set(self):
        from src.api.v1.sources import _make_list_item

        src = self._src(
            name="uploaded",
            file_storage_path="uploads/2026/05/abc-foo.pdf",
            status="ready",
            is_active=True,
        )
        item = _make_list_item(src, document_count=2, chunk_count=10)

        assert item.has_upload is True
        assert item.document_count == 2
        assert item.chunk_count == 10
        # Path itself must NEVER appear on the response model.
        dumped = item.model_dump()
        assert "file_storage_path" not in dumped

    def test_has_upload_false_when_path_none(self):
        from src.api.v1.sources import _make_list_item

        src = self._src(name="web", file_storage_path=None)
        item = _make_list_item(src)

        assert item.has_upload is False
        assert item.document_count == 0
        assert item.chunk_count == 0


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
