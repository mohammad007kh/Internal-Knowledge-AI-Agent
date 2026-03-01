"""Integration tests: full sync pipeline — T-068."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.core.container import container
from src.models.chunk import Chunk
from src.models.document import Document
from src.models.enums import SyncStatus
from src.models.sync_job import SyncJob
from src.tasks.sync_source import _sync_source_async

_TEST_DB_URL = settings.DATABASE_URL.replace("/knowledge_agent", "/test_knowledge_agent")


def _make_test_factory() -> async_sessionmaker:
    engine = create_async_engine(_TEST_DB_URL)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
class TestSyncPipeline:
    """Integration tests for _sync_source_async covering happy-path, error, and retry."""

    async def test_happy_path_creates_docs_and_chunks(
        self,
        db_session: AsyncSession,
        db_source,
        mock_langfuse,
        two_raw_docs,
    ) -> None:
        """Full pipeline run: connector returns 2 docs → SUCCESS, rows created in DB."""
        test_factory = _make_test_factory()
        fake_vector = [0.1] * 1536

        mock_source_svc = AsyncMock()
        mock_source_svc.get_source.return_value = db_source
        mock_source_svc.get_source_config.return_value = {}

        mock_connector = AsyncMock()
        mock_connector.fetch_documents.return_value = two_raw_docs

        mock_emb_svc = AsyncMock()
        mock_emb_svc.embed_texts.return_value = [fake_vector] * 20

        task_mock = MagicMock()
        task_mock.request.retries = 0
        task_mock.max_retries = 3

        with (
            container.db_session_factory.override(providers.Object(test_factory)),
            container.source_service.override(providers.Object(mock_source_svc)),
            container.embedding_service.override(providers.Object(mock_emb_svc)),
            patch("src.tasks.sync_source.AsyncSessionLocal", test_factory),
            patch("src.tasks.sync_source.ConnectorFactory") as mock_factory_cls,
        ):
            mock_factory_cls.return_value.build.return_value = mock_connector
            await _sync_source_async(task_mock, str(db_source.id))

        job_row = (
            await db_session.execute(
                select(SyncJob).where(SyncJob.source_id == db_source.id)
            )
        ).scalar_one()
        assert job_row.status == SyncStatus.SUCCESS
        assert job_row.documents_synced == 2
        assert job_row.chunks_created >= 2

        doc_rows = (
            await db_session.execute(
                select(Document).where(Document.source_id == db_source.id)
            )
        ).scalars().all()
        assert len(doc_rows) == 2

        chunk_rows = (
            await db_session.execute(
                select(Chunk).where(Chunk.source_id == db_source.id)
            )
        ).scalars().all()
        assert len(chunk_rows) >= 2
        assert all(c.embedding is not None for c in chunk_rows)

    async def test_connector_failure_marks_job_failed(
        self,
        db_session: AsyncSession,
        db_source,
        mock_langfuse,
    ) -> None:
        """ConnectorFactory.build raises → job marked FAILED, no documents persisted."""
        test_factory = _make_test_factory()

        mock_source_svc = AsyncMock()
        mock_source_svc.get_source.return_value = db_source
        mock_source_svc.get_source_config.return_value = {}

        task_mock = MagicMock()
        task_mock.request.retries = 3
        task_mock.max_retries = 3
        task_mock.retry.side_effect = RuntimeError("fetch failed")

        with (
            container.db_session_factory.override(providers.Object(test_factory)),
            container.source_service.override(providers.Object(mock_source_svc)),
            patch("src.tasks.sync_source.AsyncSessionLocal", test_factory),
            patch("src.tasks.sync_source.ConnectorFactory") as mock_factory_cls,
        ):
            mock_factory_cls.return_value.build.side_effect = RuntimeError("fetch failed")
            with pytest.raises(RuntimeError, match="fetch failed"):
                await _sync_source_async(task_mock, str(db_source.id))

        job_row = (
            await db_session.execute(
                select(SyncJob).where(SyncJob.source_id == db_source.id)
            )
        ).scalar_one()
        assert job_row.status == SyncStatus.FAILED
        assert "fetch failed" in (job_row.error_message or "")

        doc_rows = (
            await db_session.execute(
                select(Document).where(Document.source_id == db_source.id)
            )
        ).scalars().all()
        assert len(doc_rows) == 0

    async def test_source_load_failure_marks_job_failed_no_retry(
        self,
        db_session: AsyncSession,
        db_source,
        mock_langfuse,
    ) -> None:
        """get_source raises → job marked FAILED, retry is NOT called."""
        test_factory = _make_test_factory()

        mock_source_svc = AsyncMock()
        mock_source_svc.get_source.side_effect = RuntimeError("source not found")
        mock_source_svc.get_source_config.return_value = {}

        task_mock = MagicMock()
        task_mock.request.retries = 0
        task_mock.max_retries = 3

        with (
            container.db_session_factory.override(providers.Object(test_factory)),
            container.source_service.override(providers.Object(mock_source_svc)),
            patch("src.tasks.sync_source.AsyncSessionLocal", test_factory),
            patch("src.tasks.sync_source.ConnectorFactory"),
        ):
            with pytest.raises(RuntimeError, match="source not found"):
                await _sync_source_async(task_mock, str(db_source.id))

        # No retry invoked on source-load failure
        task_mock.retry.assert_not_called()

        job_row = (
            await db_session.execute(
                select(SyncJob).where(SyncJob.source_id == db_source.id)
            )
        ).scalar_one()
        assert job_row.status == SyncStatus.FAILED

    async def test_retry_path_succeeds_on_third_attempt(
        self,
        db_session: AsyncSession,
        db_source,
        mock_langfuse,
        two_raw_docs,
    ) -> None:
        """Connector fails twice, succeeds on third call → final job is SUCCESS."""
        test_factory = _make_test_factory()
        fake_vector = [0.1] * 1536
        attempt: dict[str, int] = {"count": 0}

        async def flaky_fetch():
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise RuntimeError("transient error")
            return two_raw_docs

        mock_source_svc = AsyncMock()
        mock_source_svc.get_source.return_value = db_source
        mock_source_svc.get_source_config.return_value = {}

        mock_emb_svc = AsyncMock()
        mock_emb_svc.embed_texts.return_value = [fake_vector] * 20

        mock_connector = AsyncMock()
        mock_connector.fetch_documents = flaky_fetch

        for retry_num in range(3):
            task_mock = MagicMock()
            task_mock.request.retries = retry_num
            task_mock.max_retries = 3
            task_mock.retry.side_effect = lambda exc, countdown=0: (_ for _ in ()).throw(exc)

            with (
                container.db_session_factory.override(providers.Object(test_factory)),
                container.source_service.override(providers.Object(mock_source_svc)),
                container.embedding_service.override(providers.Object(mock_emb_svc)),
                patch("src.tasks.sync_source.AsyncSessionLocal", test_factory),
                patch("src.tasks.sync_source.ConnectorFactory") as mock_factory_cls,
            ):
                mock_factory_cls.return_value.build.return_value = mock_connector
                try:
                    await _sync_source_async(task_mock, str(db_source.id))
                    break
                except RuntimeError:
                    pass

        job_row = (
            await db_session.execute(
                select(SyncJob)
                .where(SyncJob.source_id == db_source.id)
                .order_by(SyncJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        assert job_row.status == SyncStatus.SUCCESS
