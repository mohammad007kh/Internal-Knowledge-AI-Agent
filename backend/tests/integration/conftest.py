"""
Integration test fixtures - use real DB (test_knowledge_agent),
mock only external third-party services (MinIO, Celery, LLM).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SourceType, SyncStatus
from src.models.source import Source
from src.models.sync_job import SyncJob
from src.schemas.raw_document import RawDocument


@pytest.fixture(autouse=True)
def mock_minio_integration():
    """
    Mock MinIO for integration tests - DB is real, object storage is not.
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


@pytest_asyncio.fixture
async def db_source(db_session: AsyncSession) -> Source:
    """Persist a minimal Source row for integration tests."""
    src = Source(
        id=uuid.uuid4(),
        name="Integration Test Source",
        source_type=SourceType.WEB_URL,
        owner_id=uuid.uuid4(),
        is_active=True,
        config_encrypted=b"placeholder",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    return src


@pytest_asyncio.fixture
async def db_sync_job(db_session: AsyncSession, db_source: Source) -> SyncJob:
    """Persist a minimal SyncJob row linked to db_source for integration tests."""
    job = SyncJob(
        id=uuid.uuid4(),
        source_id=db_source.id,
        status=SyncStatus.PENDING,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


@pytest.fixture
def mock_langfuse():
    """Patch Langfuse inside sync_source task; yield the mock instance."""
    with patch("src.tasks.sync_source.Langfuse") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def two_raw_docs() -> list[RawDocument]:
    """Two minimal RawDocument objects for pipeline tests."""
    return [
        RawDocument(
            title="Doc A",
            content="The quick brown fox jumps over the lazy dog",
            url="https://example.com/a",
            content_hash="hash_a",
            metadata={},
        ),
        RawDocument(
            title="Doc B",
            content="Knowledge graphs enable semantic search at scale",
            url="https://example.com/b",
            content_hash="hash_b",
            metadata={},
        ),
    ]