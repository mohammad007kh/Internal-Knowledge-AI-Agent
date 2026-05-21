"""Celery task: study a database source's schema (Slice E1).

Fires on two lifecycle events:

* ``POST /sources`` for ``type=database`` — kicked off after the route's
  commit lands.
* ``PATCH /sources/{id}/credentials`` — kicked off after a successful
  credential rotation so the schema viewer reflects the new connection.

Pipeline
--------
1. Load the source; bail unless ``source_type == database``.
2. Idempotency guard — if a non-terminal :class:`SchemaStudy` already
   exists for this source, log + skip (no duplicate concurrent runs).
3. Stamp ``Source.schema_status = 'studying'`` and create a fresh
   :class:`SchemaStudy` row in state ``QUEUED``.
4. Decrypt credentials, build the :class:`DatabaseConnector`, ask it for a
   :class:`SchemaDocument` (or raise if the connector cannot produce one).
5. On success: persist the document + fingerprint, flip Source.schema_status
   to ``completed``, mark the study row READY.
6. On failure: flip Source.schema_status to ``failed``, mark the study row
   ``<phase>_FAILED`` with a sanitised error message, and return a result
   dict with ``status='failed'`` plus the phase + sanitised error. We do
   NOT retry — schema-study failures are surfaced to the admin via the
   verb column on the sources list and the schema-viewer's error pane,
   not auto-retried (a transient failure stays surfaced until the admin
   hits "Re-study schema").

Idempotency
-----------
``SchemaStudyRepository.is_running(source_id)`` is the concurrency guard.
A second worker that arrives while the first is running observes a
non-terminal row and returns ``"skipped"`` — the first worker's pipeline
keeps going untouched. Same contract as :mod:`auto_name_source`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from src.connectors.factory import ConnectorFactory
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.models.enums import SourceStatus
from src.repositories.schema_study_repository import SchemaStudyRepository
from src.repositories.source_repository import SourceRepository
from src.services.db_introspection.fingerprint import compute_fingerprint
from src.services.db_introspection.schema_doc import SchemaDocument
from src.services.sync_cancellation import (
    clear_sync_cancelled,
    is_sync_cancelled,
)
from src.tasks import celery_app

logger = logging.getLogger(__name__)


async def _study_cancelled_response(
    source_id: uuid.UUID, study_id: uuid.UUID | None, stage: str
) -> dict[str, Any]:
    """Persist the study-cancellation terminal state and return the result dict.

    Flips the source's ``schema_status`` to ``failed`` so the UI surfaces a
    retryable phase, and marks any in-flight :class:`SchemaStudy` row as
    ``<phase>_FAILED`` with a stable "Cancelled by user." message. This
    intentionally reuses the existing failure plumbing rather than adding a
    new ``CANCELLED`` state to the study state machine — the studying agent
    keeps its current vocabulary; only the SyncJob gets a new state.
    """
    async with AsyncSessionLocal() as session:
        await SourceRepository(session).set_schema_status(source_id, "failed")
        if study_id is not None:
            await SchemaStudyRepository(session).mark_failed(
                study_id, phase=stage, message="Cancelled by user."
            )
        await session.commit()
    await clear_sync_cancelled(source_id)
    logger.info(
        "study_source: cancellation honoured at stage=%s for source_id=%s",
        stage,
        source_id,
    )
    return {
        "source_id": str(source_id),
        "status": "cancelled",
        "stage": stage,
    }


# Same agent version stamp persisted on every SchemaStudy row. Bump when the
# studying-agent's pipeline contract changes so the admin viewer can render
# "agent v1.2 produced this" alongside the document. Kept in sync with
# :data:`src.services.db_introspection.sql_inspector.AGENT_VERSION` and
# :data:`src.services.db_introspection.mongo_inspector.AGENT_VERSION` — the
# inspector stamps the document, the orchestrator stamps the study row.
_AGENT_VERSION = "studying-agent@0.3"


def _sanitise(message: str) -> str:
    """Strip credentials from connection-string-like substrings.

    Mirrors the helper in :mod:`sync_source` — the studying-agent's error
    messages MUST never echo a connection string into the audit log or the
    admin UI's error surface.
    """
    return re.sub(r"://[^@\s]+@", "://***@", message)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tasks.study_source",
    max_retries=0,
)
def study_source(self: Any, source_id: str) -> dict[str, Any]:
    """Celery entry point — sync wrapper around :func:`_run`.

    Args:
        source_id: UUID string of the :class:`~src.models.source.Source` to study.

    Returns:
        Dict with ``source_id`` and one of ``status='completed'``,
        ``status='skipped'``, or ``status='failed'``.
    """
    return asyncio.run(_run(uuid.UUID(source_id)))


# ---------------------------------------------------------------------------
# Async core — directly callable from unit tests
# ---------------------------------------------------------------------------


async def _run(source_id: uuid.UUID) -> dict[str, Any]:
    """Build a :class:`SchemaDocument` for *source_id* and persist it.

    See module docstring for the full pipeline.
    """
    async with AsyncSessionLocal() as session:
        source_repo = SourceRepository(session)
        study_repo = SchemaStudyRepository(session)

        source = await source_repo.get_by_id(source_id)
        if source is None:
            logger.info(
                "study_source: source %s not found — skipping", source_id
            )
            return {"source_id": str(source_id), "status": "skipped"}

        # Only DB sources are studied. Non-DB sources reach here only via
        # a buggy enqueue site — log and bail.
        source_type_value = (
            source.source_type.value
            if hasattr(source.source_type, "value")
            else str(source.source_type)
        )
        if source_type_value != "database":
            logger.info(
                "study_source: source %s is not a database source — skipping",
                source_id,
            )
            return {"source_id": str(source_id), "status": "skipped"}

        # Idempotency guard wrapped in a Postgres advisory lock keyed on
        # source_id. Without the lock, ``is_running`` (SELECT) and
        # ``create_study`` (INSERT) are two round-trips — two workers that
        # land within milliseconds can both observe is_running=False and
        # both insert. The advisory_xact_lock serialises the gate so only
        # one INSERT goes through; the second worker takes the lock after
        # the first commits, sees the in-flight row, and short-circuits.
        # The lock auto-releases on transaction end (commit OR rollback).
        async with study_repo.lock_for_source(source_id):
            if await study_repo.is_running(source_id):
                logger.info(
                    "study_source: source %s already has a study in flight — skipping",
                    source_id,
                )
                return {"source_id": str(source_id), "status": "skipped"}

            # Mark studying + create study row in one transaction so the admin
            # UI sees the transition atomically.
            await source_repo.set_schema_status(source_id, "studying")
            study = await study_repo.create_study(
                source_id=source_id,
                agent_version=_AGENT_VERSION,
                state="QUEUED",
            )
            study_id = study.id
            await session.commit()

        # U16 checkpoint: cancel arrived between the API row commit and the
        # connector work starting. Cheap to honour here — we've only written
        # bookkeeping rows so far.
        if await is_sync_cancelled(source_id):
            return await _study_cancelled_response(
                source_id, study_id, stage="CONNECT"
            )

        # ---- Phase work happens outside the original transaction so a
        # ---- connector failure doesn't roll back the "studying" status.
        try:
            schema_document = await _produce_schema_document(source)
        except Exception as exc:  # noqa: BLE001 — terminal: persist + re-raise
            sanitised = _sanitise(str(exc))
            phase = _phase_from_exception(exc)
            logger.warning(
                "study_source: study %s failed at phase=%s",
                study_id,
                phase,
                exc_info=True,
            )
            async with AsyncSessionLocal() as fail_session:
                await SourceRepository(fail_session).set_schema_status(
                    source_id, "failed"
                )
                await SchemaStudyRepository(fail_session).mark_failed(
                    study_id, phase=phase, message=sanitised
                )
                await fail_session.commit()
            return {
                "source_id": str(source_id),
                "status": "failed",
                "phase": phase,
                "error": sanitised,
            }

        # U16 checkpoint: cancel arrived during the (potentially long) schema
        # study — we have the document in hand, but the admin asked us to
        # stop. Honour the request rather than persist a document the user
        # said they didn't want. Leaves the source in 'failed' so the UI
        # surfaces a retryable phase.
        if await is_sync_cancelled(source_id):
            return await _study_cancelled_response(
                source_id, study_id, stage="DESCRIBING"
            )

        # ---- Persist success in a fresh session.
        # FX32 — flip Source.status='ready' atomically with
        # schema_status='completed' + the study row's mark_completed. DB
        # sources never produce chunks or last_synced_at, so the frontend's
        # derivePhase rule-6 fallback (no job + no chunks + no
        # last_synced_at → pending_upload) would otherwise leave a fully
        # studied DB source stuck in pending_upload forever, blocking the
        # admin from approving it for users. The studying agent IS what
        # makes a DB source "ready", mirroring how a successful sync makes
        # a file/web source "ready" — be explicit about it.
        async with AsyncSessionLocal() as success_session:
            doc_json = schema_document.model_dump(mode="json")
            await SchemaStudyRepository(success_session).mark_completed(
                study_id,
                schema_document_json=doc_json,
                fingerprint=schema_document.fingerprint,
                partial=schema_document.partial,
            )
            source_repo_success = SourceRepository(success_session)
            await source_repo_success.set_schema_status(
                source_id, "completed"
            )
            await source_repo_success.set_status(source_id, SourceStatus.READY)
            await success_session.commit()

        logger.info(
            "study_source: completed source_id=%s study_id=%s",
            source_id,
            study_id,
        )
        return {"source_id": str(source_id), "status": "completed"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _produce_schema_document(source: Any) -> SchemaDocument:
    """Drive the connector to produce a :class:`SchemaDocument`.

    The connector contract is duck-typed: any object with an awaitable
    ``study_schema()`` method that returns a :class:`SchemaDocument` is
    acceptable. Today only the database connector exposes this; if the
    method is absent we raise so the failure is surfaced through the
    standard FAILED state path rather than silently writing an empty doc.
    """
    decrypted_config = _decrypt_config(source)
    connector = ConnectorFactory().build(
        source_type=source.source_type,
        source_id=str(source.id),
        decrypted_config=decrypted_config,
    )
    study_schema = getattr(connector, "study_schema", None)
    if study_schema is None:
        raise NotImplementedError(
            "Connector does not implement study_schema() — cannot study this "
            "source's schema."
        )

    raw = await study_schema()

    # Strict validation at the type boundary — a connector that lies about
    # its output shape fails loudly here rather than corrupting the
    # persisted JSON.
    if isinstance(raw, SchemaDocument):
        document = raw
    else:
        document = SchemaDocument.model_validate(raw)

    # Always recompute the fingerprint from the canonical algorithm so we
    # never trust a connector-supplied digest.
    fingerprint = compute_fingerprint(document)
    if document.fingerprint != fingerprint:
        document = document.model_copy(update={"fingerprint": fingerprint})
    return document


def _decrypt_config(source: Any) -> dict[str, Any]:
    """Fernet-decrypt the source's connection config.

    Inlines the same primitive used by :class:`SourceService._decrypt_config`
    so the celery task doesn't need to construct a session-bound service
    just to access the Fernet key.
    """
    if source.config_encrypted is None:
        return {}
    import json  # noqa: PLC0415

    from cryptography.fernet import Fernet  # noqa: PLC0415

    fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    decrypted: str = fernet.decrypt(source.config_encrypted).decode()
    return dict(json.loads(decrypted))


def _phase_from_exception(exc: BaseException) -> str:
    """Map an exception to the agent phase that owns it.

    The :data:`~src.models.schema_study.STUDY_STATES` vocabulary has
    ``<PHASE>_FAILED`` entries — ``CONNECT_FAILED``, ``INVENTORY_FAILED``,
    ``COLUMNS_FAILED``, etc. The state is stamped via ``mark_failed`` as
    ``f"{phase}_FAILED"``, so the phase string we return here is the
    PREFIX of one of those states (NOT the in-flight phase name from
    :data:`~src.models.schema_study.STUDY_PHASES`, which uses ``CONNECTING``).

    Resolution order:

    1. :class:`~src.services.db_introspection._errors.SchemaStudyPhaseError`
       carries an explicit ``.phase`` (already a failed-state prefix) — the
       inspector knows best, so trust it.
    2. ConnectionError / TimeoutError → CONNECT (network / auth class).
    3. Anything else (incl. NotImplementedError for non-SQL connectors) →
       INVENTORY — the safest "something went wrong early" bucket.
    """
    from src.services.db_introspection._errors import (  # noqa: PLC0415
        SchemaStudyPhaseError,
    )

    if isinstance(exc, SchemaStudyPhaseError):
        return exc.phase
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "CONNECT"
    return "INVENTORY"
