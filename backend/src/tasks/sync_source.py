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
from datetime import datetime, timezone
from typing import Any

from langfuse import Langfuse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.connectors.factory import ConnectorFactory
from src.connectors.web_url_errors import WebUrlFetchError
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
from src.services.sync_cancellation import (
    clear_sync_cancelled,
    is_sync_cancelled,
)
from src.services.sync_job_service import SyncJobService
from src.tasks import celery_app

logger = logging.getLogger(__name__)


_CANCEL_RESULT_MARKER = "cancelled"


async def _bail_if_cancelled(
    *,
    source_id: str,
    job_id: uuid.UUID,
    job_svc: SyncJobService,
    stage: str,
) -> dict[str, Any] | None:
    """Cooperative-cancellation checkpoint helper (U16).

    Returns a result dict when the cancel flag is set and the task should
    exit cleanly; returns ``None`` to keep going. The flag is cleared once
    a checkpoint honours it so a follow-up sync of the same source starts
    fresh even if Redis TTL has not yet elapsed.
    """
    if not await is_sync_cancelled(source_id):
        return None
    logger.info(
        "sync_source: cancellation observed at stage=%s for source_id=%s "
        "job_id=%s — exiting cleanly",
        stage,
        source_id,
        job_id,
    )
    await job_svc.mark_cancelled(
        job_id, error_message=f"Cancelled by user during {stage}."
    )
    await clear_sync_cancelled(source_id)
    return {
        "source_id": source_id,
        "status": _CANCEL_RESULT_MARKER,
        "stage": stage,
    }


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

    # U16 checkpoint: cancel requested before the task even started running.
    # Catches the queued-job path where the API endpoint set the flag before
    # the worker picked up the task off the broker.
    early = await _bail_if_cancelled(
        source_id=source_id,
        job_id=job_id,
        job_svc=job_svc,
        stage="pre_start",
    )
    if early is not None:
        trace.update(output=early)
        langfuse.flush()
        return early

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
    # Database sources have no documents to ingest — the agent queries them
    # at retrieval time via text_to_query. So "Sync now" / "Re-study schema"
    # on a DB source doesn't fetch+chunk; instead it (a) records a zero-count
    # SyncJob for the admin's history and (b) enqueues the studying-agent
    # task (slice E1) so the schema document is (re)built. This is what
    # makes the "Re-study schema" affordance on the Overview actually do
    # something — the studying task is idempotent (SchemaStudyRepository
    # .is_running) so a duplicate enqueue is harmless.
    if str(source.source_type) == "database" or getattr(
        source.source_type, "value", None
    ) == "database":
        logger.info(
            "sync_source: DB source %s — skipping fetch, enqueueing studying agent",
            source_id,
        )
        # U16 checkpoint: a DB-source sync is very fast (it only enqueues
        # the study task) but still worth honouring if the admin pressed
        # Stop before the worker picked the task up. Catches the queued
        # cancellation of a re-study request.
        db_cancel = await _bail_if_cancelled(
            source_id=source_id,
            job_id=job_id,
            job_svc=job_svc,
            stage="pre_db_dispatch",
        )
        if db_cancel is not None:
            trace.update(output=db_cancel)
            langfuse.flush()
            return db_cancel

        await job_svc.mark_success(
            job_id,
            documents_synced=0,
            chunks_created=0,
        )
        study_enqueued = False
        try:
            from src.tasks.study_source import (  # noqa: PLC0415
                study_source as _study,
            )

            _study.delay(source_id)
            study_enqueued = True
        except ImportError:
            # A module-level import failure is a broken deployment, not a
            # transient broker outage — surface it.
            logger.error(
                "study_source module failed to import — deployment broken",
                exc_info=True,
            )
            raise
        except Exception:  # noqa: BLE001
            logger.warning(
                "study_source enqueue failed for source_id=%s (broker?) — "
                "sync recorded, schema NOT re-studied",
                source_id,
                exc_info=True,
            )
        result_db: dict[str, Any] = {
            "source_id": source_id,
            "documents_synced": 0,
            "chunks_created": 0,
            "skipped_reason": "db_source_uses_live_retrieval",
            "study_enqueued": study_enqueued,
        }
        trace.update(output={"status": "success", **result_db})
        langfuse.flush()
        return result_db

    # U16 checkpoint: skip the (potentially long) fetch when the admin has
    # already pressed Stop. Cheaper than reading the whole remote index just
    # to throw it away.
    pre_fetch = await _bail_if_cancelled(
        source_id=source_id,
        job_id=job_id,
        job_svc=job_svc,
        stage="pre_fetch",
    )
    if pre_fetch is not None:
        trace.update(output=pre_fetch)
        langfuse.flush()
        return pre_fetch

    span_fetch = trace.span(name="fetch_documents")
    try:
        connector = ConnectorFactory().build(
            source_type=source.source_type,
            source_id=str(source.id),
            decrypted_config=decrypted_config,
        )
        raw_docs: list[RawDocument] = await connector.fetch_documents()
    except WebUrlFetchError as exc:
        # FX25 — connector raises a permanent, user-actionable failure mode.
        # The exception carries an already-sanitised, user-visible message;
        # we stamp it onto the SyncJob verbatim and DO NOT retry — retrying
        # a 404, an SSRF block, or a JS-only SPA shell won't help.
        msg = exc.user_message
        span_fetch.end(output={"error": msg, "reason": exc.reason.value})
        trace.update(output={"status": "failed", "error": msg})
        langfuse.flush()
        await job_svc.mark_failed(job_id, error_message=msg)
        return {
            "source_id": source_id,
            "status": "failed",
            "error": msg,
            "reason": exc.reason.value,
        }
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
                # U16 per-doc checkpoint. Placed at the TOP of the loop so a
                # cancel observed mid-batch retains every fully-processed
                # document on commit + bails before the next iteration's
                # Document row is created. The session.commit() below runs
                # only on the cancellation path's clean exit branch.
                if await is_sync_cancelled(source_id):
                    logger.info(
                        "sync_source: cancellation observed mid-chunking — "
                        "committing %d documents and exiting",
                        documents_synced,
                    )
                    # Persist any chunks accumulated so far for already-
                    # processed Documents BEFORE the cancel. Without this,
                    # the per-doc rows would commit but their chunks would
                    # be lost — leaving zero-chunk Documents in the DB.
                    if all_chunk_texts:
                        vectors_partial = await embedding_svc.embed_texts(
                            all_chunk_texts
                        )
                        await chunk_repo.bulk_create(
                            [
                                Chunk(
                                    document_id=doc_id,
                                    source_id=src_id,
                                    chunk_text=all_chunk_texts[idx],
                                    embedding=vectors_partial[idx],
                                    chunk_index=chunk_index,
                                    metadata_=meta,
                                    embedder_id=active_embedder_id,
                                )
                                for idx, (
                                    doc_id,
                                    src_id,
                                    chunk_index,
                                    meta,
                                ) in enumerate(pending_chunks)
                            ]
                        )
                    await session.commit()
                    await job_svc.mark_cancelled(
                        job_id,
                        error_message="Cancelled by user during chunking.",
                    )
                    await clear_sync_cancelled(source_id)
                    span_process.end(
                        output={
                            "documents_synced": documents_synced,
                            "chunks_created": len(pending_chunks),
                            "cancelled": True,
                        }
                    )
                    result_cancelled: dict[str, Any] = {
                        "source_id": source_id,
                        "status": _CANCEL_RESULT_MARKER,
                        "stage": "chunking",
                        "documents_synced": documents_synced,
                        "chunks_created": len(pending_chunks),
                    }
                    trace.update(output=result_cancelled)
                    langfuse.flush()
                    return result_cancelled

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

            # U16 checkpoint: last chance to bail before the (potentially
            # large) bulk-embed call. The chunking loop above has already
            # exited, so the work-completed-so-far semantics is preserved
            # by persisting Documents + Chunks via the same session.commit
            # below — but if cancel arrived during the loop above, we
            # already returned. This checkpoint catches the case where
            # cancel lands between the loop ending and the embed starting.
            if await is_sync_cancelled(source_id):
                logger.info(
                    "sync_source: cancellation observed before bulk-embed "
                    "— skipping embedding, retaining %d documents",
                    documents_synced,
                )
                # Documents are already in the session; commit them
                # without chunks so the source has the new files even
                # though they aren't indexed yet. The admin can re-sync to
                # finish the embedding.
                await session.commit()
                await job_svc.mark_cancelled(
                    job_id,
                    error_message="Cancelled by user before embedding.",
                )
                await clear_sync_cancelled(source_id)
                span_process.end(
                    output={
                        "documents_synced": documents_synced,
                        "chunks_created": 0,
                        "cancelled": True,
                    }
                )
                result_pre_embed: dict[str, Any] = {
                    "source_id": source_id,
                    "status": _CANCEL_RESULT_MARKER,
                    "stage": "pre_embed",
                    "documents_synced": documents_synced,
                    "chunks_created": 0,
                }
                trace.update(output=result_pre_embed)
                langfuse.flush()
                return result_pre_embed

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

    # U16 final checkpoint: a cancel that lands between the embed completing
    # and the success commit still has a clean exit path. The Documents +
    # Chunks have already committed inside the session above, so we just
    # flip the job row and exit. The source ends up in a fully-indexed
    # state — admins won't see a "Cancelled" sync that actually finished,
    # because we honour the flag deterministically here.
    final_check = await _bail_if_cancelled(
        source_id=source_id,
        job_id=job_id,
        job_svc=job_svc,
        stage="pre_success",
    )
    if final_check is not None:
        final_check["documents_synced"] = documents_synced
        final_check["chunks_created"] = chunks_created
        trace.update(output=final_check)
        langfuse.flush()
        return final_check

    # ── 7. Mark job success ───────────────────────────────────────────────────
    await job_svc.mark_success(
        job_id,
        documents_synced=documents_synced,
        chunks_created=chunks_created,
    )

    # ── 7b. Flip source.status='ready' + stamp last_synced_at (FX35a) ────────
    # Symmetric to study_source's set_status('ready') (FX32a). Without this,
    # file/web sources stayed source.status='pending' forever — derivePhase's
    # no-job fallback (rule 8: source.status==='ready') never fired and the
    # lifecycle was stuck at pending_upload. Wrapped in try/except: a flip
    # failure must NOT undo the success commit above; the source will catch
    # up on the next sync.
    try:
        async with session_factory() as flip_session:
            await SourceRepository(flip_session).mark_ready_after_sync(
                uuid.UUID(source_id), datetime.now(timezone.utc)
            )
            await flip_session.commit()
    except Exception:  # noqa: BLE001 — best-effort flip; must not undo the success commit
        logger.warning(
            "sync_source: post-success status flip failed for source %s — "
            "lifecycle may stay pending until next sync",
            source_id,
            exc_info=True,
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
