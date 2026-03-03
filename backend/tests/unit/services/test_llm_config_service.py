"""Unit tests for LLMConfigService — T-090."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.exceptions import NotFoundError
from src.services.llm_config_service import LLMConfigService


# ---------------------------------------------------------------------------
# Local fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def llm_config_service(mock_llm_repo):
    return LLMConfigService(llm_repo=mock_llm_repo)


def _make_slot(slot_id=None, slot_name="default", is_default=True):
    from unittest.mock import MagicMock

    slot = MagicMock()
    slot.id = slot_id or uuid.uuid4()
    slot.slot_name = slot_name
    slot.is_default = is_default
    return slot


# ---------------------------------------------------------------------------
# TestCRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    async def test_create_slot_encrypts_api_key(
        self, llm_config_service, mock_llm_repo
    ):
        """create_slot with api_key calls _encrypt_value and persists."""
        slot = _make_slot()
        mock_llm_repo.create = AsyncMock(return_value=slot)

        with patch(
            "src.services.llm_config_service._encrypt_value",
            return_value=b"enc_key",
        ) as mock_encrypt:
            result = await llm_config_service.create_slot(
                slot_name="gpt4",
                provider="openai",
                model_name="gpt-4",
                api_key="sk-secret",
            )

        mock_encrypt.assert_called_once_with("sk-secret")
        mock_llm_repo.create.assert_called_once()
        assert result is slot

    async def test_create_slot_without_api_key(
        self, llm_config_service, mock_llm_repo
    ):
        """create_slot without api_key does not call _encrypt_value."""
        slot = _make_slot()
        mock_llm_repo.create = AsyncMock(return_value=slot)

        with patch(
            "src.services.llm_config_service._encrypt_value"
        ) as mock_encrypt:
            result = await llm_config_service.create_slot(
                slot_name="gpt4-noapikey",
                provider="openai",
                model_name="gpt-4",
            )

        mock_encrypt.assert_not_called()
        assert result is slot

    async def test_update_slot_raises_not_found(
        self, llm_config_service, mock_llm_repo
    ):
        """update_slot raises NotFoundError when slot does not exist."""
        mock_llm_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await llm_config_service.update_slot(
                uuid.uuid4(), model_name="gpt-4-turbo"
            )

    async def test_update_slot_re_encrypts_api_key(
        self, llm_config_service, mock_llm_repo
    ):
        """update_slot with api_key in kwargs re-encrypts it."""
        existing = _make_slot()
        mock_llm_repo.get_by_id = AsyncMock(return_value=existing)
        mock_llm_repo.update = AsyncMock(return_value=existing)

        with patch(
            "src.services.llm_config_service._encrypt_value",
            return_value=b"re_enc",
        ) as mock_encrypt:
            await llm_config_service.update_slot(
                existing.id, api_key="new-secret"
            )

        mock_encrypt.assert_called_once_with("new-secret")

    async def test_delete_slot_raises_not_found(
        self, llm_config_service, mock_llm_repo
    ):
        """delete_slot raises NotFoundError when slot does not exist."""
        mock_llm_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await llm_config_service.delete_slot(uuid.uuid4())

    async def test_delete_slot_removes_record(
        self, llm_config_service, mock_llm_repo
    ):
        """delete_slot calls repo.delete when slot exists."""
        slot = _make_slot()
        mock_llm_repo.get_by_id = AsyncMock(return_value=slot)
        mock_llm_repo.delete = AsyncMock()

        await llm_config_service.delete_slot(slot.id)

        mock_llm_repo.delete.assert_called_once_with(slot.id)


# ---------------------------------------------------------------------------
# TestHotReload
# ---------------------------------------------------------------------------

class TestHotReload:
    async def test_get_default_slot_returns_current_default(
        self, llm_config_service, mock_llm_repo
    ):
        """get_default_slot delegates to repo.get_default()."""
        slot = _make_slot(is_default=True)
        mock_llm_repo.get_default = AsyncMock(return_value=slot)

        result = await llm_config_service.get_default_slot()

        mock_llm_repo.get_default.assert_called_once()
        assert result is slot


# ---------------------------------------------------------------------------
# TestPerSourceOverride
# ---------------------------------------------------------------------------

class TestPerSourceOverride:
    async def test_set_source_override_calls_upsert(
        self, llm_config_service, mock_llm_repo
    ):
        """set_source_override calls repo.upsert_source_override."""
        slot = _make_slot()
        source_id = uuid.uuid4()
        mock_llm_repo.get_by_id = AsyncMock(return_value=slot)
        mock_llm_repo.upsert_source_override = AsyncMock(return_value=slot)

        result = await llm_config_service.set_source_override(source_id, slot.id)

        mock_llm_repo.upsert_source_override.assert_called_once()
        assert result is slot

    async def test_set_source_override_raises_not_found_when_slot_missing(
        self, llm_config_service, mock_llm_repo
    ):
        """set_source_override raises NotFoundError if slot_id is invalid."""
        mock_llm_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await llm_config_service.set_source_override(uuid.uuid4(), uuid.uuid4())

    async def test_get_slot_for_source_returns_override(
        self, llm_config_service, mock_llm_repo
    ):
        """get_slot_for_source returns source-specific slot when available."""
        slot = _make_slot(is_default=False)
        source_id = uuid.uuid4()
        mock_llm_repo.get_by_source_id = AsyncMock(return_value=slot)

        result = await llm_config_service.get_slot_for_source(source_id)

        mock_llm_repo.get_by_source_id.assert_called_once_with(source_id)
        assert result is slot

    async def test_get_slot_for_source_falls_back_to_default(
        self, llm_config_service, mock_llm_repo
    ):
        """get_slot_for_source falls back to default when no override exists."""
        default_slot = _make_slot(is_default=True)
        source_id = uuid.uuid4()
        mock_llm_repo.get_by_source_id = AsyncMock(return_value=None)
        mock_llm_repo.get_default = AsyncMock(return_value=default_slot)

        result = await llm_config_service.get_slot_for_source(source_id)

        mock_llm_repo.get_default.assert_called_once()
        assert result is default_slot
