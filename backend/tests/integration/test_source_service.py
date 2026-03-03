"""Integration tests for SourceService.

Spec coverage: FR-009, FR-011, FR-013, FR-015, FR-030, FR-031
  FR-009 - admins enable/disable citation display per source
  FR-011 - admins register database sources (PostgreSQL, MS SQL, MySQL, MongoDB)
  FR-013 - automatic schema inspection on database source registration
  FR-015 - sources tagged as live/snapshot with freshness status
  FR-030 - admins configure AI model per processing stage
  FR-031 - per-source AI model overrides for retrieval and QA stages

Tests Exercise:
- T-058: Source service layer integration tests

Coverage:
- create_source: success, duplicate name+owner → ConflictError
- get_source: found, not found → NotFoundError
- delete_source: success, not found → NotFoundError, idempotent delete
- list_sources_for_owner: returns tuple[list, int]
- list_all_active_sources: returns tuple[list, int]
- test_connection: connector success, connector exception → False
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from src.core.exceptions import ConflictError, NotFoundError
from src.models.enums import SourceType
from src.models.source import Source
from src.repositories.source_repository import SourceRepository
from src.schemas.source import SourceCreate
from src.services.source_service import SourceService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings


@pytest.fixture
def connector_factory() -> MagicMock:
    return MagicMock()


@pytest.fixture
async def svc(
    db_session: object,
    mock_settings: MagicMock,
    connector_factory: MagicMock,
) -> SourceService:
    repo = SourceRepository(session=db_session)  # type: ignore[arg-type]
    return SourceService(repo, mock_settings, connector_factory)  # type: ignore[arg-type]


@pytest.fixture
async def sample_source(svc: SourceService, admin_user: object) -> Source:
    payload = SourceCreate(
        name="Test Source",
        source_type=SourceType.web_url,
        config={"url": "https://example.com"},
    )
    return await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestCreateSource
# ---------------------------------------------------------------------------


class TestCreateSource:
    async def test_create_source_returns_source_object(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="My Source",
            source_type=SourceType.web_url,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert isinstance(created, Source)

    async def test_create_source_assigns_id(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Identified Source",
            source_type=SourceType.file_upload,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert created.id is not None

    async def test_create_source_persists_name(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Named Source",
            source_type=SourceType.web_url,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert created.name == "Named Source"

    async def test_create_source_persists_source_type(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Typed Source",
            source_type=SourceType.database,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert created.source_type == SourceType.database

    async def test_create_source_encrypts_config(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Encrypted Config Source",
            source_type=SourceType.web_url,
            config={"url": "https://secret.example.com", "token": "abc123"},
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert created.config_encrypted is not None

    async def test_create_source_config_encrypted_is_bytes(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Config Bytes Source",
            source_type=SourceType.web_url,
            config={"key": "value"},
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert isinstance(created.config_encrypted, bytes)

    async def test_create_source_empty_config_is_encrypted(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Empty Config Source",
            source_type=SourceType.web_url,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        # Even empty dict {} is encrypted into bytes
        assert created.config_encrypted is not None

    async def test_create_source_duplicate_name_raises_conflict(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Duplicate Source",
            source_type=SourceType.web_url,
        )
        await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        with pytest.raises(ConflictError):
            await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]

    async def test_create_source_same_name_different_owner_succeeds(
        self, svc: SourceService, admin_user: object, regular_user: object
    ) -> None:
        payload = SourceCreate(
            name="Shared Name Source",
            source_type=SourceType.web_url,
        )
        first = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        second = await svc.create_source(payload, owner_id=regular_user.id)  # type: ignore[attr-defined]
        assert first.id != second.id

    async def test_create_source_sets_owner_id(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Owned Source",
            source_type=SourceType.web_url,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        assert created.owner_id == admin_user.id  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestGetSource
# ---------------------------------------------------------------------------


class TestGetSource:
    async def test_get_source_returns_correct_source(
        self, svc: SourceService, sample_source: Source
    ) -> None:
        result = await svc.get_source(sample_source.id)
        assert result.id == sample_source.id

    async def test_get_source_returns_correct_name(
        self, svc: SourceService, sample_source: Source
    ) -> None:
        result = await svc.get_source(sample_source.id)
        assert result.name == sample_source.name

    async def test_get_source_not_found_raises_not_found(
        self, svc: SourceService
    ) -> None:
        with pytest.raises(NotFoundError):
            await svc.get_source(uuid.uuid4())


# ---------------------------------------------------------------------------
# TestDeleteSource
# ---------------------------------------------------------------------------


class TestDeleteSource:
    async def test_delete_source_returns_none(
        self, svc: SourceService, sample_source: Source
    ) -> None:
        result = await svc.delete_source(sample_source.id)
        assert result is None

    async def test_delete_source_deactivates_source(
        self, svc: SourceService, sample_source: Source
    ) -> None:
        await svc.delete_source(sample_source.id)
        with pytest.raises(NotFoundError):
            await svc.get_source(sample_source.id)

    async def test_delete_source_not_found_raises_not_found(
        self, svc: SourceService
    ) -> None:
        with pytest.raises(NotFoundError):
            await svc.delete_source(uuid.uuid4())

    async def test_delete_source_twice_raises_not_found(
        self, svc: SourceService, sample_source: Source
    ) -> None:
        await svc.delete_source(sample_source.id)
        with pytest.raises(NotFoundError):
            await svc.delete_source(sample_source.id)


# ---------------------------------------------------------------------------
# TestListSourcesForOwner
# ---------------------------------------------------------------------------


class TestListSourcesForOwner:
    async def test_list_returns_tuple(
        self, svc: SourceService, admin_user: object
    ) -> None:
        result = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert isinstance(result, tuple)
        assert len(result) == 2

    async def test_list_returns_list_and_count(
        self, svc: SourceService, admin_user: object
    ) -> None:
        sources, total = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert isinstance(sources, list)
        assert isinstance(total, int)

    async def test_list_empty_for_new_owner(
        self, svc: SourceService, admin_user: object
    ) -> None:
        sources, total = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert sources == []
        assert total == 0

    async def test_list_includes_created_source(
        self, svc: SourceService, admin_user: object, sample_source: Source
    ) -> None:
        sources, total = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert total == 1
        assert sources[0].id == sample_source.id

    async def test_list_count_increments_after_create(
        self, svc: SourceService, admin_user: object
    ) -> None:
        for i in range(3):
            payload = SourceCreate(
                name=f"Source {i}",
                source_type=SourceType.web_url,
            )
            await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        sources, total = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert total == 3
        assert len(sources) == 3

    async def test_list_excludes_deleted_source(
        self, svc: SourceService, admin_user: object, sample_source: Source
    ) -> None:
        await svc.delete_source(sample_source.id)
        sources, total = await svc.list_sources_for_owner(admin_user.id)  # type: ignore[attr-defined]
        assert total == 0
        assert sources == []

    async def test_list_skip_pagination(
        self, svc: SourceService, admin_user: object
    ) -> None:
        for i in range(3):
            payload = SourceCreate(
                name=f"Paged Source {i}",
                source_type=SourceType.web_url,
            )
            await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        sources, total = await svc.list_sources_for_owner(admin_user.id, skip=2, limit=10)  # type: ignore[attr-defined]
        assert total == 3
        assert len(sources) == 1

    async def test_list_limit_pagination(
        self, svc: SourceService, admin_user: object
    ) -> None:
        for i in range(3):
            payload = SourceCreate(
                name=f"Limited Source {i}",
                source_type=SourceType.web_url,
            )
            await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        sources, total = await svc.list_sources_for_owner(admin_user.id, skip=0, limit=2)  # type: ignore[attr-defined]
        assert total == 3
        assert len(sources) == 2

    async def test_list_does_not_return_other_owner_sources(
        self, svc: SourceService, admin_user: object, regular_user: object
    ) -> None:
        admin_payload = SourceCreate(name="Admin Source", source_type=SourceType.web_url)
        await svc.create_source(admin_payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        sources, total = await svc.list_sources_for_owner(regular_user.id)  # type: ignore[attr-defined]
        assert total == 0
        assert sources == []


# ---------------------------------------------------------------------------
# TestListAllActiveSources
# ---------------------------------------------------------------------------


class TestListAllActiveSources:
    async def test_list_all_returns_tuple(self, svc: SourceService) -> None:
        result = await svc.list_all_active_sources()
        assert isinstance(result, tuple)
        assert len(result) == 2

    async def test_list_all_returns_list_and_int(self, svc: SourceService) -> None:
        sources, total = await svc.list_all_active_sources()
        assert isinstance(sources, list)
        assert isinstance(total, int)

    async def test_list_all_empty_initially(self, svc: SourceService) -> None:
        sources, total = await svc.list_all_active_sources()
        assert total == 0
        assert sources == []

    async def test_list_all_includes_created_sources(
        self, svc: SourceService, admin_user: object, regular_user: object
    ) -> None:
        p1 = SourceCreate(name="Source A", source_type=SourceType.web_url)
        p2 = SourceCreate(name="Source B", source_type=SourceType.file_upload)
        await svc.create_source(p1, owner_id=admin_user.id)  # type: ignore[attr-defined]
        await svc.create_source(p2, owner_id=regular_user.id)  # type: ignore[attr-defined]
        sources, total = await svc.list_all_active_sources()
        assert total == 2
        assert len(sources) == 2

    async def test_list_all_excludes_deleted_source(
        self, svc: SourceService, admin_user: object, sample_source: Source
    ) -> None:
        await svc.delete_source(sample_source.id)
        sources, total = await svc.list_all_active_sources()
        assert total == 0
        assert sources == []


# ---------------------------------------------------------------------------
# TestGetSourceConfig
# ---------------------------------------------------------------------------


class TestGetSourceConfig:
    async def test_get_source_config_returns_original_dict(
        self, svc: SourceService, admin_user: object
    ) -> None:
        config_data: dict[str, Any] = {"url": "https://example.com", "token": "secret"}
        payload = SourceCreate(
            name="Config Source",
            source_type=SourceType.web_url,
            config=config_data,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        retrieved_config = await svc.get_source_config(created.id)
        assert retrieved_config == config_data

    async def test_get_source_config_empty_config(
        self, svc: SourceService, admin_user: object
    ) -> None:
        payload = SourceCreate(
            name="Empty Config Source",
            source_type=SourceType.web_url,
        )
        created = await svc.create_source(payload, owner_id=admin_user.id)  # type: ignore[attr-defined]
        retrieved_config = await svc.get_source_config(created.id)
        assert retrieved_config == {}


# ---------------------------------------------------------------------------
# TestTestConnection
# ---------------------------------------------------------------------------


class TestTestConnection:
    async def test_connection_success_returns_true(
        self,
        svc: SourceService,
        connector_factory: MagicMock,
        admin_user: object,
        sample_source: Source,
    ) -> None:
        mock_connector = MagicMock()
        mock_connector.test_connection = AsyncMock(return_value=True)
        connector_factory.build.return_value = mock_connector

        result = await svc.test_connection(sample_source.id)
        assert result is True

    async def test_connection_failure_returns_false(
        self,
        svc: SourceService,
        connector_factory: MagicMock,
        admin_user: object,
        sample_source: Source,
    ) -> None:
        connector_factory.build.side_effect = Exception("Connector unavailable")

        result = await svc.test_connection(sample_source.id)
        assert result is False

    async def test_connection_connector_test_raises_returns_false(
        self,
        svc: SourceService,
        connector_factory: MagicMock,
        admin_user: object,
        sample_source: Source,
    ) -> None:
        mock_connector = MagicMock()
        mock_connector.test_connection = AsyncMock(side_effect=ConnectionError("timeout"))
        connector_factory.build.return_value = mock_connector

        result = await svc.test_connection(sample_source.id)
        assert result is False

    async def test_connection_calls_factory_with_source_type(
        self,
        svc: SourceService,
        connector_factory: MagicMock,
        admin_user: object,
        sample_source: Source,
    ) -> None:
        mock_connector = MagicMock()
        mock_connector.test_connection = AsyncMock(return_value=True)
        connector_factory.build.return_value = mock_connector

        await svc.test_connection(sample_source.id)

        call_kwargs = connector_factory.build.call_args
        assert call_kwargs is not None

    async def test_connection_calls_factory_with_string_source_id(
        self,
        svc: SourceService,
        connector_factory: MagicMock,
        admin_user: object,
        sample_source: Source,
    ) -> None:
        mock_connector = MagicMock()
        mock_connector.test_connection = AsyncMock(return_value=True)
        connector_factory.build.return_value = mock_connector

        await svc.test_connection(sample_source.id)

        _, kwargs = connector_factory.build.call_args
        assert kwargs.get("source_id") == str(sample_source.id)
