"""Shared fixtures for chat integration tests."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

if _INTEGRATION:
    from tests.conftest import get_access_token  # noqa: E402

    @pytest.fixture()
    def mock_openai_client() -> AsyncMock:
        mock = AsyncMock()
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = "Here is the answer."
        completion.usage.prompt_tokens = 100
        completion.usage.completion_tokens = 20
        mock.chat.completions.create.return_value = completion
        return mock

    @pytest.fixture()
    def mock_langfuse() -> MagicMock:
        lf = MagicMock()
        lf.span.return_value = MagicMock()
        lf.trace.return_value = MagicMock()
        return lf

    @pytest.fixture()
    def mock_embedding_service() -> AsyncMock:
        svc = AsyncMock()
        svc.embed_texts.return_value = [[0.1] * 1536]
        return svc

    @pytest_asyncio.fixture()
    async def user_token(client, regular_user) -> str:  # noqa: ARG001
        return await get_access_token(client, "user@example.com", "User@12345")

    @pytest_asyncio.fixture()
    async def admin_token(client, admin_user) -> str:  # noqa: ARG001
        return await get_access_token(client, "admin@example.com", "Admin@1234")
