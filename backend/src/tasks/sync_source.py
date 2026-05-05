"""Celery task: sync a single knowledge-source (T-064).

Pipeline
--------
1. Create a SyncJob record (status=PENDING → RUNNING).
2. Retrieve source + decrypt config via SourceService.
3. Build connector → fetch_documents() → list[RawDocument].
4. For each RawDocument:
   a. Chunk the content via ChunkingService.
   b. Persist a Document ORM row (source_id, raw_text, metadata_).
   c. Collect ChunkData objects.
5. Batch-embed all chunks via EmbeddingService.
6. Batch-persist Chunk ORM rows via ChunkRepository.
7. Mark job SUCCESS (documents_synced, chunks_created).
8. On any non-retriable error → mark job FAILED and re-raise.
9. Retry up to 3 times with exponential back-off.
10. Instrumentation via Langfuse traces/spans.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from langfuse import Langfuse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.connectors.factory import ConnectorFactory
from src.core.config import settings
from src.core.container import container
from src.core.database import task_engine
from src.models.chunk import Chunk
from src.models.document import Document
from src.repositories.chunk_repository import ChunkRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.source_repository import SourceRepository
from src.repositories.sync_job_repository import SyncJobRepository
from src.schemas.raw_document import RawDocument
from src.services.embedding_service_factory import EmbeddingServiceFactory
from src.services.source_service import SourceService
from src.services.sync_job_service import SyncJobService
from src.tasks import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sanitise(message: str) -> str:
    """Strip credentials from connection-string-like strings in error messages."""
    return re.sub(r"://[^@\s]+@", "://***@", message)


# ---------------------------------------------------------------------------
# Async pipeline
# ---------------------------------------------------------------------------


async def _sync_source_async(task: Any, source_id: str) -> dict[str, Any]:  # noqa: C901
    """Full sync pipeline; runs inside ``asyncio.run()``.

    All DB access happens through a per-task ``AsyncEngine`` created inside
    the current event loop. The container's module-level engine is NOT used
    here — see ``src.core.database.task_engine`` for the rationale.
    """

    langfuse = Langfuse()
    trace = langfuse.trace(  # type: ignore[attr-defined]
        name="sync_source",
        input={"source_id": source_id},
    )

    # ``task_engine`` lives for the entire task — every service below uses
    # this single engine + sessionmaker so all asyncpg connections bind to
    # this loop and get disposed cleanly when the context exits.
    async with task_engine() as eng:
        session_factory = async_sessionmaker(
            eng, class_=AsyncSession, expire_on_commit=False
        )

        # Build per-task services bound to the per-task engine.
        # SyncJobService takes a session_factory directly, matching the
        # request-scoped pattern used elsewhere.
        sync_job_repo = SyncJobRepository()
        job_svc = SyncJobService(
            session_factory=session_factory,
            sync_job_repo=sync_job_repo,
        )

        # SourceService takes a SourceRepository bound to a single session;
        # one session per service-call is fine here because the task is
        # short-lived and we never share the source object across sessions.
        source_session = session_factory()
        source_svc = SourceService(
            source_repo=SourceRepository(source_session),
            settings=settings,
            connector_factory=ConnectorFactory(),
        )

        # EmbeddingServiceFactory needs the same per-task session_factory so
        # its embedder lookups don't reach back into the module-level engine.
        embedding_factory = EmbeddingServiceFactory(
            session_factory=session_factory,
        )

        # Stateless services come from the container — they hold no DB engine
        # references (chunking is pure Python; only embedding clients are
        # event-loop sensitive but we build them via the per-task factory above).
        chunking_svc = container.chunking_service()

        try:
            return await _run_sync_pipeline(
                task=task,
                source_id=source_id,
                trace=trace,
                langfuse=langfuse,
                job_svc=job_svc,
                source_svc=source_svc,
                embedding_factory=embedding_factory,
                chunking_svc=chunking_svc,
                session_factory=session_factory,
            )
        finally:
            await source_session.close()
            # Close any embedder httpx clients opened in this loop.
            try:
                await embedding_factory.aclose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.warning(
                    "embedding_factory.aclose() failed in sync_source task",
                    exc_info=True,
                )


async def _run_sync_pipeline(  # noqa: C901
    *,
    task: Any,
    source_id: str,
    trace: Any,
    langfuse: Langfuse,
    job_svc: SyncJobService,
    source_svc: SourceService,
    embedding_factory: EmbeddingServiceFactory,
    chunking_svc: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Inner pipeline body — extracted to keep the engine-lifecycle wrapper thin."""
    # ── 1. Create SyncJob ────────────────────────────────────────────────────
    job = await job_svc.create_job(uuid.UUID(source_id))
    job_id = job.id
    await job_svc.mark_running(job_id)

    # ── 2. Retrieve source + config ──────────────────────────────────────────
    span_meta = trace.span(name="load_source_metadata")
    try:
        source = await source_svc.get_source(uuid.UUID(source_id))
        decrypted_config = await source_svc.get_source_config(uuid.UUID(source_id))
    except Exception as exc:
        span_meta.end(output={"error": _sanitise(str(exc))})
        trace.update(output={"status": "failed", "error": _sanitise(str(exc))})
        langfuse.flush()
        await job_svc.mark_failed(job_id, error_message=_sanitise(str(exc)))
        raise
    span_meta.end(output={"source_type": source.source_type})

    # ── 3. Fetch raw documents ───────────────────────────────────────────────
    span_fetch = trace.span(name="fetch_documents")
    try:
        connector = ConnectorFactory().build(
            source_type=source.source_type,
            source_id=str(source.id),
            decrypted_config=decrypted_config,
        )
        raw_docs: list[RawDocument] = await connector.fetch_documents()
    except Exception as exc:
        sanitised = _sanitise(str(exc))
        span_fetch.end(output={"error": sanitised})
        trace.update(output={"status": "failed", "error": sanitised})
        langfuse.flush()
        await job_svc.mark_failed(job_id, error_message=sanitised)
        raise task.retry(exc=exc, countdown=2 ** task.request.retries)
    span_fetch.end(output={"raw_doc_count": len(raw_docs)})

    # ── 4–6. Chunk → persist documents → embed → persist chunks ─────────────
    span_process = trace.span(name="process_documents")
    # ``for_source`` returns both the service and the embedder id used to
    # stamp ``embedder_id`` onto each persisted chunk — single DB roundtrip.
    embedding_svc, active_embedder_id = await embedding_factory.for_source(
        uuid.UUID(source_id)
    )

    all_chunk_texts: list[str] = []
    # Parallel lists kept in sync so we can back-fill embeddings later.
    pending_chunks: list[tuple[uuid.UUID, uuid.UUID, int, dict[str, Any]]] = []
    # (document_id, source_id, chunk_index, metadata)

    documents_synced = 0

    try:
        async with session_factory() as session:
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            for raw_doc in raw_docs:
                # Persist Document
                doc_orm = Document(
                    source_id=source.id,
                    raw_text=raw_doc.content,
                    metadata_={
                        "title": raw_doc.title,
                        "url": raw_doc.url,
                        "content_hash": raw_doc.content_hash,
                        **raw_doc.metadata,
                    },
                )
                doc_orm = await doc_repo.create(doc_orm)
                documents_synced += 1

                # Chunk document
                # Enrich metadata so retrieve.py can project document_title /
                # source_name / page_number into the chunk dict — otherwise
                # citations in persist.py degrade to source_id (UUID).
                chunk_data_list = chunking_svc.chunk_text(
                    raw_doc.content,
                    metadata={
                        "source_id": str(source.id),
                        "url": raw_doc.url,
                        "document_title": raw_doc.title,
                        "source_name": source.name,
                        "page_number": raw_doc.metadata.get("page_number"),
                    },
                )
                for c in chunk_data_list:
                    all_chunk_texts.append(c.text)
                    pending_chunks.append(
                        (doc_orm.id, source.id, c.chunk_index, c.metadata)
                    )

            # Batch embed all chunk texts
            vectors: list[list[float]] = []
            if all_chunk_texts:
                vectors = await embedding_svc.embed_texts(all_chunk_texts)

            # Persist all Chunks in one bulk call
            if pending_chunks:
                chunk_orm_list = [
                    Chunk(
                        document_id=doc_id,
                        source_id=src_id,
                        chunk_text=all_chunk_texts[idx],
                        embedding=vectors[idx],
                        chunk_index=chunk_index,
                        metadata_=meta,
                        embedder_id=active_embedder_id,
                    )
                    for idx, (doc_id, src_id, chunk_index, meta) in enumerate(
                        pending_chunks
                    )
                ]
                await chunk_repo.bulk_create(chunk_orm_list)

            await session.commit()

    except Exception as exc:
        sanitised = _sanitise(str(exc))
        span_process.end(output={"error": sanitised})
        trace.update(output={"status": "failed", "error": sanitised})
        langfuse.flush()
        await job_svc.mark_failed(job_id, error_message=sanitised)
        raise task.retry(exc=exc, countdown=2 ** task.request.retries)

    chunks_created = len(pending_chunks)
    span_process.end(
        output={
            "documents_synced": documents_synced,
            "chunks_created": chunks_created,
        }
    )

    # ── 7. Mark job success ───────────────────────────────────────────────────
    await job_svc.mark_success(
        job_id,
        documents_synced=documents_synced,
        chunks_created=chunks_created,
    )

    result: dict[str, Any] = {
        "source_id": source_id,
        "documents_synced": documents_synced,
        "chunks_created": chunks_created,
    }
    trace.update(output={"status": "success", **result})
    langfuse.flush()
    logger.info(
        "sync_source completed source_id=%s docs=%d chunks=%d",
        source_id,
        documents_synced,
        chunks_created,
    )
    return result


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tasks.sync_source",
    max_retries=3,
)
def sync_source(self: Any, source_id: str) -> dict[str, Any]:
    """Synchronise a single knowledge-source.

    Args:
        source_id: UUID string of the :class:`~src.models.source.Source` to sync.

    Returns:
        Dict with ``source_id``, ``documents_synced``, and ``chunks_created``.
    """
    return asyncio.run(_sync_source_async(self, source_id))
