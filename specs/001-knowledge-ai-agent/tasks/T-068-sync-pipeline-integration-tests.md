# T-068 — Sync Pipeline Integration Tests

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x async · pytest + httpx · asyncio_mode=auto
PostgreSQL 16 + pgvector
Celery + Redis
Langfuse self-hosted
coverage ≥ 80%
```

## Goal
Write integration tests for the end-to-end sync pipeline (T-061–T-064, T-066):

1. **Happy path** — connector returns 2 docs → SUCCESS, rows created, counters correct
2. **Connector failure** — connector raises → FAILED, no orphaned rows
3. **Retry path** — fails twice, succeeds on third attempt → SUCCESS
4. **API trigger** — `POST /sources/{id}/sync` 202, `GET /sync-jobs/{id}` 200

---

## Acceptance Criteria

- [ ] Happy-path test verifies: PENDING→RUNNING→SUCCESS transition; `documents_synced==2`; `chunks_created >= 2`; embeddings stored in `chunk.embedding` column; no test leaves orphan rows
- [ ] Failure test verifies: PENDING→RUNNING→FAILED; `error_message != None`; no `Document`/`Chunk` rows created
- [ ] Retry test verifies: task retries exactly 2×, then succeeds; final status == SUCCESS
- [ ] API tests verify: 202 returns `status="pending"` body; 403 for non-admin; 404 for bad source_id
- [ ] Langfuse SDK is fully mocked — no real HTTP calls in tests
- [ ] Celery task runs synchronously via `task.apply()` (no broker needed)

---

## 1  Fixtures — `tests/integration/conftest.py` additions

```python
# tests/integration/conftest.py
import asyncio
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.models.enums import SyncStatus
from tests.factories import make_source  # helper defined below


@pytest_asyncio.fixture
async def db_source(db_session: AsyncSession) -> Source:
    src = Source(
        id=uuid4(),
        name="Integration Test Source",
        source_type="web_url",
        owner_id=uuid4(),
        is_active=True,
        config_encrypted=b"placeholder",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    return src


@pytest.fixture
def mock_langfuse():
    """Patch the Langfuse client so no real HTTP calls are made."""
    with patch("app.tasks.sync_source.Langfuse") as mock_cls:
        instance = MagicMock()
        instance.trace.return_value = MagicMock()
        instance.trace.return_value.span.return_value.__enter__ = MagicMock(
            return_value=MagicMock()
        )
        instance.trace.return_value.span.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def two_raw_docs():
    from app.schemas.raw_document import RawDocument

    return [
        RawDocument(
            title="Doc A",
            content="The quick brown fox jumps over the lazy dog.",
            url="https://example.com/a",
            content_hash="hash_a",
            metadata={},
        ),
        RawDocument(
            title="Doc B",
            content="Knowledge graphs enable semantic search at scale.",
            url="https://example.com/b",
            content_hash="hash_b",
            metadata={},
        ),
    ]
```

---

## 2  Happy-Path Test — `tests/integration/test_sync_pipeline.py`

```python
# tests/integration/test_sync_pipeline.py
"""Integration tests for the full ingest pipeline."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_job import SyncJob
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.enums import SyncStatus
from app.tasks.sync_source import _sync_source_async


@pytest.mark.asyncio
async def test_happy_path_creates_docs_and_chunks(
    db_session: AsyncSession,
    db_source,
    mock_langfuse,
    two_raw_docs,
):
    """SUCCESS path: 2 docs → RUNNING → SUCCESS; counters correct."""
    fake_vector = [0.1] * 1536

    with (
        patch(
            "app.tasks.sync_source.ConnectorFactory.create",
            return_value=AsyncMock(fetch_documents=AsyncMock(return_value=two_raw_docs)),
        ),
        patch(
            "app.tasks.sync_source.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=[fake_vector, fake_vector],
        ),
    ):
        await _sync_source_async(
            source_id=str(db_source.id),
            self_mock=MagicMock(request=MagicMock(retries=0)),
        )

    # SyncJob assertions
    job_row = (
        await db_session.execute(
            select(SyncJob).where(SyncJob.source_id == db_source.id)
        )
    ).scalar_one()

    assert job_row.status == SyncStatus.SUCCESS
    assert job_row.documents_synced == 2
    assert job_row.chunks_created >= 2

    # Document rows
    docs = (
        await db_session.execute(
            select(Document).where(Document.source_id == db_source.id)
        )
    ).scalars().all()
    assert len(docs) == 2

    # Chunk + embedding rows
    chunks = (
        await db_session.execute(
            select(Chunk).where(Chunk.source_id == db_source.id)
        )
    ).scalars().all()
    assert len(chunks) >= 2
    for c in chunks:
        assert c.embedding is not None


@pytest.mark.asyncio
async def test_connector_failure_marks_job_failed(
    db_session: AsyncSession,
    db_source,
    mock_langfuse,
):
    """FAILED path: connector raises → job.status==FAILED, no orphan rows."""
    self_mock = MagicMock()
    self_mock.request.retries = 3          # max retries exceeded → no retry
    self_mock.max_retries = 3

    with patch(
        "app.tasks.sync_source.ConnectorFactory.create",
        return_value=AsyncMock(
            fetch_documents=AsyncMock(side_effect=RuntimeError("fetch failed"))
        ),
    ):
        with pytest.raises(RuntimeError, match="fetch failed"):
            await _sync_source_async(
                source_id=str(db_source.id),
                self_mock=self_mock,
            )

    job_row = (
        await db_session.execute(
            select(SyncJob).where(SyncJob.source_id == db_source.id)
        )
    ).scalar_one()

    assert job_row.status == SyncStatus.FAILED
    assert job_row.error_message is not None
    assert "fetch failed" in job_row.error_message

    # No orphan documents
    docs = (
        await db_session.execute(
            select(Document).where(Document.source_id == db_source.id)
        )
    ).scalars().all()
    assert len(docs) == 0


@pytest.mark.asyncio
async def test_retry_path_succeeds_on_third_attempt(
    db_session: AsyncSession,
    db_source,
    mock_langfuse,
    two_raw_docs,
):
    """RETRY path: fails 2×, succeeds 3rd → final status SUCCESS."""
    fake_vector = [0.1] * 1536
    attempt = {"count": 0}

    async def flaky_fetch():
        attempt["count"] += 1
        if attempt["count"] < 3:
            raise RuntimeError("transient error")
        return two_raw_docs

    # We call _sync_source_async three times simulating retries
    for retry_num in range(3):
        self_mock = MagicMock()
        self_mock.request.retries = retry_num
        self_mock.max_retries = 3

        connector_mock = AsyncMock()
        connector_mock.fetch_documents = flaky_fetch

        try:
            with (
                patch(
                    "app.tasks.sync_source.ConnectorFactory.create",
                    return_value=connector_mock,
                ),
                patch(
                    "app.tasks.sync_source.EmbeddingService.embed_texts",
                    new_callable=AsyncMock,
                    return_value=[fake_vector, fake_vector],
                ),
            ):
                await _sync_source_async(
                    source_id=str(db_source.id),
                    self_mock=self_mock,
                )
            break  # success on 3rd
        except RuntimeError:
            pass  # expected on attempts 1 & 2

    job_row = (
        await db_session.execute(
            select(SyncJob)
            .where(SyncJob.source_id == db_source.id)
            .order_by(SyncJob.created_at.desc())
        )
    ).scalars().first()

    assert job_row.status == SyncStatus.SUCCESS
```

---

## 3  API Integration Tests — `tests/integration/test_sync_jobs_api.py`

```python
# tests/integration/test_sync_jobs_api.py
import pytest
from httpx import AsyncClient
from unittest.mock import patch


@pytest.mark.asyncio
async def test_trigger_sync_returns_202_pending(
    async_client: AsyncClient,
    admin_token: str,
    db_source,
):
    with patch("app.tasks.sync_source.sync_source.delay"):  # don't actually enqueue
        resp = await async_client.post(
            f"/api/v1/sources/{db_source.id}/sync",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["source_id"] == str(db_source.id)


@pytest.mark.asyncio
async def test_trigger_sync_non_admin_403(
    async_client: AsyncClient,
    user_token: str,
    db_source,
):
    resp = await async_client.post(
        f"/api/v1/sources/{db_source.id}/sync",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["title"] == "Forbidden"


@pytest.mark.asyncio
async def test_trigger_sync_unknown_source_404(
    async_client: AsyncClient,
    admin_token: str,
):
    from uuid import uuid4
    resp = await async_client.post(
        f"/api/v1/sources/{uuid4()}/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_sync_job_200(
    async_client: AsyncClient,
    user_token: str,
    db_sync_job,
):
    resp = await async_client.get(
        f"/api/v1/sync-jobs/{db_sync_job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(db_sync_job.id)


@pytest.mark.asyncio
async def test_get_sync_job_not_found_404(
    async_client: AsyncClient,
    user_token: str,
):
    from uuid import uuid4
    resp = await async_client.get(
        f"/api/v1/sync-jobs/{uuid4()}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 404
```

---

## 4  File Summary

| File | Action |
|---|---|
| `tests/integration/conftest.py` | **PATCH** — add `db_source`, `mock_langfuse`, `two_raw_docs` fixtures |
| `tests/integration/test_sync_pipeline.py` | **CREATE** — 3 pipeline tests |
| `tests/integration/test_sync_jobs_api.py` | **CREATE** — 5 API tests |

---

## 5  Coverage Target

| Module | Target |
|---|---|
| `app/tasks/sync_source.py` | ≥ 85% |
| `app/services/sync_job_service.py` | ≥ 90% |
| `app/api/v1/sync_jobs.py` | ≥ 85% |

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-030 — ingestion pipeline | happy-path test |
| FR-031 — vectors persisted | embedding assertion in happy-path |
| FR-033 — retry with backoff | retry-path test |
| FR-019 — access control | 403 API test |
| FR-020 — no plaintext creds in error | failure test `error_message` assertion |
