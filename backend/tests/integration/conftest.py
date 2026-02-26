"""
Integration test fixtures — use real DB (test_knowledge_agent),
mock only external third-party services (MinIO, Celery, LLM).
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def mock_minio_integration():
    """
    Mock MinIO for integration tests — DB is real, object storage is not.
    Prevents test failures when MinIO is not running in CI.
    """
    with patch("src.core.storage.minio_client", new=MagicMock()) as mock:
        mock.presigned_put_object = MagicMock(return_value="http://mock-presigned-url")
        mock.get_object = AsyncMock(return_value=b"mock-file-content")
        yield mock


@pytest.fixture(autouse=True)
def mock_celery_integration():
    """Mock Celery task dispatch to avoid actually enqueueing tasks."""
    with patch("src.worker.tasks.celery_app.send_task", new=MagicMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_llm_integration():
    """Mock LLM API calls to avoid costs and external dep in integration tests."""
    with patch("src.agents.llm.ChatOpenAI", new=MagicMock()) as mock:
        yield mock
