# T-064 — Celery Sync-Source Task

## Context
```
Python 3.12 | Celery + Redis | SQLAlchemy 2.x async | dependency-injector
LangGraph pipeline stages: fetch → chunk → embed → persist
Langfuse self-hosted — every task run MUST emit one root trace + per-stage spans
FR-019 source access control | FR-020 no plaintext conn strings in logs
FR-033 max_retries=3, exponential backoff | FR-035 file size limit 50 MB
```

## Goal
Implement the Celery task `tasks.sync_source` that runs the full ingestion pipeline
for a single source: create sync job → fetch documents → chunk → embed → persist
Document + Chunk rows → mark success/failure.

---

## Acceptance Criteria

- [ ] Task name: `"tasks.sync_source"` — `bind=True`, `max_retries=3`
- [ ] Full pipeline: fetch → chunk → embed → bulk-insert Documents + Chunks
- [ ] Every run emits one Langfuse root trace; per-stage spans (fetch / chunk / embed / persist)
- [ ] ALL exceptions trigger `mark_failed` + `self.retry(countdown=2**retries)` up to max
- [ ] After max retries exhausted: final `mark_failed`, no further retry
- [ ] Plaintext connection strings NEVER appear in task logs (FR-020)

---

## 1  Celery Application — `app/tasks/__init__.py`

```python
# app/tasks/__init__.py
"""Celery application factory."""
from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app: Celery = Celery(
    "knowledge_ai",
    broker=_settings.redis.url,
    backend=_settings.redis.url,
)

celery_app.config_from_object("app.tasks.celeryconfig")
celery_app.autodiscover_tasks(["app.tasks"])
```

---

## 2  Celery Config — `app/tasks/celeryconfig.py`

```python
# app/tasks/celeryconfig.py
"""Celery configuration (non-beat schedules live in T-065)."""
from __future__ import annotations

# Serialization
task_serializer    = "json"
result_serializer  = "json"
accept_content     = ["json"]

# Reliability
task_acks_late                 = True
task_reject_on_worker_lost     = True
task_default_retry_delay       = 60        # seconds; overridden per-task
worker_prefetch_multiplier     = 1         # one task at a time per worker
worker_max_tasks_per_child     = 50        # recycle workers to prevent memory leaks

# Timeouts
task_soft_time_limit = 600   # 10 min — SIGTERM
task_time_limit      = 660   # 11 min — SIGKILL

# Result backend
result_expires = 86_400      # 24 h

# Routing
task_default_queue = "default"
```

---

## 3  Sync-Source Task — `app/tasks/sync_source.py`

```python
# app/tasks/sync_source.py
"""Celery task: full ingestion pipeline for a single source."""
from __future__ import annotations

import logging
from uuid import UUID

from celery import Task
from langfuse import Langfuse

from app.containers import ApplicationContainer
from app.models.enums import SyncStatus
from app.tasks import celery_app

logger = logging.getLogger(__name__)


def _container() -> ApplicationContainer:
    return ApplicationContainer()   # DI resolves shared singletons


@celery_app.task(
    bind=True,
    name="tasks.sync_source",
    max_retries=3,
    acks_late=True,
)
def sync_source(self: Task, source_id: str) -> dict:
    """
    Ingest all documents for *source_id*.

    Parameters
    ----------
    source_id:
        String UUID of the :class:`Source` to sync.

    Returns
    -------
    dict
        ``{"status": "success", "documents_synced": N, "chunks_created": M}``
    """
    import asyncio

    return asyncio.run(_sync_source_async(self, source_id))


# ─────────────────────────────────────────────────────────────── async core


async def _sync_source_async(task: Task, source_id: str) -> dict:
    container = _container()

    sync_job_svc  = await container.sync_job_service()
    source_svc    = await container.source_service()
    connector_fac = await container.connector_factory()
    chunking_svc  = await container.chunking_service()
    embedding_svc = await container.embedding_service()
    doc_repo      = await container.document_repository()
    chunk_repo    = await container.chunk_repository()
    session_factory = container.db().session_factory

    langfuse = Langfuse()
    trace = langfuse.trace(
        name="sync_source",
        metadata={"source_id": source_id, "attempt": task.request.retries + 1},
    )

    job = await sync_job_svc.create_job(UUID(source_id))
    job_id = job.id

    try:
        await sync_job_svc.mark_running(job_id)

        # ── Stage 1: fetch ────────────────────────────────────────────────
        span_fetch = trace.span(name="fetch")
        source = await source_svc.get_source(UUID(source_id))
        connector = connector_fac.build(source)
        raw_docs = await connector.fetch_documents()  # list[RawDocument]
        span_fetch.end(output={"document_count": len(raw_docs)})

        # ── Stage 2: chunk ────────────────────────────────────────────────
        span_chunk = trace.span(name="chunk")
        all_chunks: list[tuple[int, "ChunkData"]] = []  # (doc_idx, chunk)
        doc_chunk_counts: list[int] = []
        for doc_idx, raw_doc in enumerate(raw_docs):
            chunks = chunking_svc.chunk_text(
                raw_doc.content,
                metadata={"source_id": source_id, "doc_title": raw_doc.title},
            )
            doc_chunk_counts.append(len(chunks))
            for c in chunks:
                all_chunks.append((doc_idx, c))
        total_chunks = len(all_chunks)
        span_chunk.end(output={"total_chunks": total_chunks})

        # ── Stage 3: embed ────────────────────────────────────────────────
        span_embed = trace.span(name="embed")
        texts = [c.text for _, c in all_chunks]
        vectors = await embedding_svc.embed_texts(texts)
        span_embed.end(output={"vectors_created": len(vectors)})

        # ── Stage 4: persist ─────────────────────────────────────────────
        span_persist = trace.span(name="persist")
        async with session_factory() as session:
            doc_ids: list[UUID] = []
            for raw_doc in raw_docs:
                doc = await doc_repo.create(
                    session,
                    source_id=UUID(source_id),
                    title=raw_doc.title,
                    url=raw_doc.url,
                    content_hash=raw_doc.content_hash,
                )
                doc_ids.append(doc.id)

            for idx, (doc_idx, chunk_data) in enumerate(all_chunks):
                await chunk_repo.create(
                    session,
                    document_id=doc_ids[doc_idx],
                    chunk_index=chunk_data.chunk_index,
                    text=chunk_data.text,
                    embedding=vectors[idx],
                    metadata=chunk_data.metadata,
                )
            await session.commit()
        span_persist.end(
            output={
                "documents_persisted": len(raw_docs),
                "chunks_persisted": total_chunks,
            }
        )

        await sync_job_svc.mark_success(
            job_id,
            documents_synced=len(raw_docs),
            chunks_created=total_chunks,
        )
        trace.update(output={"status": "success"})
        langfuse.flush()

        return {
            "status": "success",
            "documents_synced": len(raw_docs),
            "chunks_created": total_chunks,
        }

    except Exception as exc:  # noqa: BLE001
        _err_msg = _sanitise(str(exc))  # FR-020 — strip conn strings
        logger.exception("sync_source failed for source=%s: %s", source_id, _err_msg)

        await sync_job_svc.mark_failed(job_id, error_message=_err_msg)
        trace.update(output={"status": "failed", "error": _err_msg})
        langfuse.flush()

        retries = task.request.retries
        if retries < task.max_retries:
            raise task.retry(exc=exc, countdown=2**retries)
        # max retries exhausted — raise to move task to FAILURE state
        raise


# ─────────────────────────────────────────────────────────────── helpers


def _sanitise(message: str) -> str:
    """
    Strip patterns that might contain plaintext connection strings (FR-020).

    Replaces substrings matching ``://<user>:<password>@`` with ``://***@``.
    """
    import re

    return re.sub(r"://[^@\s]+@", "://***@", message)
```

---

## 4  `RawDocument` dataclass — `app/schemas/raw_document.py`

```python
# app/schemas/raw_document.py
"""Intermediate representation returned by connector.fetch_documents()."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RawDocument:
    title:        str
    content:      str
    url:          str = ""
    content_hash: str = ""
    metadata:     dict = field(default_factory=dict)
```

---

## 5  Update `BaseConnector` — `app/connectors/base.py` patch

```python
# -- patch abstract method signature --

from app.schemas.raw_document import RawDocument

class BaseConnector(ABC):
    ...
    @abstractmethod
    async def fetch_documents(self) -> list[RawDocument]:
        """Return raw documents from the external source."""
```

---

## 6  `containers.py` patch

Add `celery_app` as an accessible attribute (not a provider):

```python
# -- at module level, after imports --
from app.tasks import celery_app as _celery_app

class ApplicationContainer(DeclarativeContainer):
    ...
    @property
    def celery_app(self):
        return _celery_app
```

---

## 7  Dependencies — `requirements.txt` additions

```
celery>=5.4.0
langfuse>=2.34.0
```

---

## 8  Unit Tests — `tests/unit/test_sync_source_task.py`

```python
# tests/unit/test_sync_source_task.py
"""Unit tests for _sanitise helper and task wiring."""
from __future__ import annotations

import pytest
from app.tasks.sync_source import _sanitise


class TestSanitise:
    def test_strips_credentials(self):
        raw = "postgresql+asyncpg://admin:s3cr3t@db:5432/mydb"
        assert _sanitise(raw) == "postgresql+asyncpg://***@db:5432/mydb"

    def test_multiple_occurrences(self):
        raw = "redis://user:pw@redis:6379 and postgresql://u:p@pg:5432"
        result = _sanitise(raw)
        assert "pw" not in result
        assert ":p@" not in result

    def test_no_credentials_unchanged(self):
        raw = "some error message without URL"
        assert _sanitise(raw) == raw

    def test_empty_string(self):
        assert _sanitise("") == ""
```

---

## 9  Verification Checklist

```bash
pytest tests/unit/test_sync_source_task.py -v
# Expected: 4 tests passing

# Import check (Docker container)
python -c "from app.tasks.sync_source import sync_source; print('task OK:', sync_source.name)"
# Expected: task OK: tasks.sync_source
celery -A app.tasks.celery_app inspect registered
# Expected: tasks.sync_source in the list
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-030 — document ingestion pipeline | full fetch→chunk→embed→persist pipeline |
| FR-031 — vector embeddings persisted | `embed_texts()` → `chunk_repo.create(embedding=…)` |
| FR-033 — max retries 3, backoff | `max_retries=3`, `countdown=2**retries` |
| FR-019 — source access | pipeline processes only the requested `source_id` |
| FR-020 — no plaintext conn strings | `_sanitise()` applied to all error messages |
| Langfuse tracing | root trace + fetch/chunk/embed/persist spans |
