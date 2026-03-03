"""Integration tests for SourceRepository — T-058 File 1.

Spec coverage: FR-012, FR-014
  FR-012 - admins register document sources by uploading files (PDF, Word, Excel)
  FR-014 - admins trigger re-inspection of source schema/content at any time

Guard: these tests require a live PostgreSQL instance and are skipped
unless the RUN_INTEGRATION_TESTS=1 environment variable is set.
"""
from __future__ import annotations

import os
import uuid

import pytest

from src.models.enums import SourceType
from src.models.source import Source
from src.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def repo(db_session: object) -> SourceRepository:  # type: ignore[type-arg]
    return SourceRepository(session=db_session)  # type: ignore[arg-type]


@pytest.fixture
async def sample_source(repo: SourceRepository, admin_user: object) -> Source:  # type: ignore[type-arg]
    return await repo.create(
        name="Test Source",
        source_type=SourceType.WEB_URL,
        config_encrypted=b"encrypted-placeholder",
        owner_id=admin_user.id,  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_creates_source_returns_with_id(self, repo: SourceRepository, admin_user: object) -> None:  # type: ignore[type-arg]
        created = await repo.create(
            name="New Source",
            source_type=SourceType.FILE_UPLOAD,
            config_encrypted=b"enc",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        assert created is not None
        assert created.id is not None

    async def test_creates_source_persists_name(self, repo: SourceRepository, admin_user: object) -> None:  # type: ignore[type-arg]
        created = await repo.create(
            name="KW Source",
            source_type=SourceType.DATABASE,
            config_encrypted=b"enc2",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        assert created.name == "KW Source"

    async def test_created_source_is_active(self, repo: SourceRepository, admin_user: object) -> None:  # type: ignore[type-arg]
        created = await repo.create(
            name="Active Source",
            source_type=SourceType.WEB_URL,
            config_encrypted=b"x",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        assert created.is_active is True


# ---------------------------------------------------------------------------
# TestRead
# ---------------------------------------------------------------------------


class TestRead:
    async def test_get_by_id_returns_source(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        fetched = await repo.get_by_id(sample_source.id)
        assert fetched is not None
        assert fetched.id == sample_source.id
        assert fetched.name == sample_source.name

    async def test_get_by_id_returns_none_for_invalid(self, repo: SourceRepository) -> None:
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_deactivated_source_excluded_from_list_active(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        deactivated = await repo.deactivate(sample_source.id)
        assert deactivated is True
        results = await repo.list_active()
        ids = [s.id for s in results]
        assert sample_source.id not in ids

    async def test_deactivated_source_still_returned_by_get_by_id(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        """get_by_id ignores is_active flag."""
        await repo.deactivate(sample_source.id)
        found = await repo.get_by_id(sample_source.id)
        assert found is not None
        assert found.is_active is False

    async def test_list_active_excludes_inactive(
        self, repo: SourceRepository, admin_user: object  # type: ignore[type-arg]
    ) -> None:
        active = await repo.create(
            name="Active",
            source_type=SourceType.WEB_URL,
            config_encrypted=b"x",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        inactive = await repo.create(
            name="Inactive",
            source_type=SourceType.WEB_URL,
            config_encrypted=b"x",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        await repo.deactivate(inactive.id)
        results = await repo.list_active()
        result_ids = [s.id for s in results]
        assert active.id in result_ids
        assert inactive.id not in result_ids


# ---------------------------------------------------------------------------
# TestPagination
# ---------------------------------------------------------------------------


class TestPagination:
    async def test_list_active_pagination(
        self, repo: SourceRepository, admin_user: object  # type: ignore[type-arg]
    ) -> None:
        # Create 3 sources
        for i in range(3):
            await repo.create(
                name=f"Page Source {i}",
                source_type=SourceType.WEB_URL,
                config_encrypted=b"x",
                owner_id=admin_user.id,  # type: ignore[attr-defined]
            )

        page1 = await repo.list_active(skip=0, limit=2)
        page2 = await repo.list_active(skip=2, limit=2)

        assert len(page1) == 2
        # page2 has remainder (at least 1)
        assert len(page2) >= 1

    async def test_list_by_owner(
        self, repo: SourceRepository, admin_user: object, regular_user: object  # type: ignore[type-arg]
    ) -> None:
        await repo.create(
            name="Owner Source A",
            source_type=SourceType.WEB_URL,
            config_encrypted=b"x",
            owner_id=admin_user.id,  # type: ignore[attr-defined]
        )
        await repo.create(
            name="Owner Source B",
            source_type=SourceType.FILE_UPLOAD,
            config_encrypted=b"x",
            owner_id=regular_user.id,  # type: ignore[attr-defined]
        )
        admin_sources = await repo.list_by_owner(admin_user.id)  # type: ignore[attr-defined]
        user_sources = await repo.list_by_owner(regular_user.id)  # type: ignore[attr-defined]

        assert all(s.owner_id == admin_user.id for s in admin_sources)  # type: ignore[attr-defined]
        assert all(s.owner_id == regular_user.id for s in user_sources)  # type: ignore[attr-defined]
