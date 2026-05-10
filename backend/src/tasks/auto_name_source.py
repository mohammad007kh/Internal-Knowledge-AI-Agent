"""Celery task: name a source from its ingested content.

Fires on two lifecycle events:

* :meth:`SyncJobService.mark_success` enqueues this task whenever a sync
  finishes for a source whose ``name_status='pending_ai'`` (file uploads,
  web URLs, Confluence, SharePoint).
* The DB studying agent will enqueue this task on its
  ``READY``/``READY_PARTIAL`` transition (wired in a follow-up commit).

Pipeline:

1. Build a :class:`SourceProfile` via the source-type-specific profiler
   (chunk sampling for files, SchemaDocument projection for databases).
2. Pass the profile to :class:`SourceNamingService` for the shared LLM
   step that returns ``{name, description}``.
3. Persist on the Source row, flip ``name_status`` and
   ``description_status`` to ``ai_set``, and append a row to
   ``source_description_history`` so the AI write is auditable.

Idempotent: if the source's status is no longer ``pending_ai`` (admin
typed something while we were working, or the task already ran), the
task short-circuits and returns ``"skipped"``. This keeps the worker
safe against duplicate enqueues from overlapping lifecycle events.

Retries: ``autoretry_for=(Exception,)`` with exponential backoff up to
three attempts. Terminal failure leaves the row at ``pending_ai`` so the
admin can hit "Regenerate" or the next sync re-fires the hook.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.models.source import Source
from src.models.source_description_history import SourceDescriptionHistory
from src.services.source_profiling import SourceProfilerFactory
from src.services.source_profiling.database_profiler import DatabaseSourceProfiler
from src.services.source_profiling.file_profiler import FileSourceProfiler
from src.tasks import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public Celery task
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tasks.auto_name_source",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def auto_name_source(self, source_id: str) -> dict[str, Any]:  # noqa: ANN001
    """Celery entry point. Sync wrapper around :func:`_run` so we play
    well with Celery's process-pool worker (which doesn't run an event
    loop unless we ask it to)."""
    return asyncio.run(_run(uuid.UUID(source_id)))


# ---------------------------------------------------------------------------
# Async core — easy to unit-test by calling directly with an in-memory session
# ---------------------------------------------------------------------------


async def _run(source_id: uuid.UUID) -> dict[str, Any]:
    """Build a profile, generate a name+description, persist it.

    Returns a small status dict for Celery result backend / Langfuse.
    """
    async with AsyncSessionLocal() as session:
        source = await _load_pending_source(session, source_id)
        if source is None:
            logger.info(
                "auto_name_source: source %s no longer pending — skipping",
                source_id,
            )
            return {"source_id": str(source_id), "status": "skipped"}

        profiler_factory = _build_profiler_factory()
        profiler = profiler_factory.for_source(source)
        profile = await profiler.profile(source, session)

        # F7 splice point — this stub is replaced once SourceNamingService
        # lands. Keep the call shape stable so the splice is one line.
        ai_name, ai_description = await _generate_name_and_description(profile)

        await _persist_ai_naming(
            session,
            source=source,
            ai_name=ai_name,
            ai_description=ai_description,
        )
        await session.commit()

    logger.info(
        "auto_name_source: completed",
        extra={
            "source_id": str(source_id),
            "ai_name_len": len(ai_name),
            "ai_description_len": len(ai_description),
        },
    )
    return {
        "source_id": str(source_id),
        "status": "ai_set",
        "name": ai_name,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_pending_source(
    session: AsyncSession, source_id: uuid.UUID
) -> Source | None:
    """Load the source iff its ``name_status`` is still ``pending_ai``,
    holding a row-level lock so concurrent workers don't double-process.

    ``with_for_update(skip_locked=True)`` means a worker that arrives
    second on the same row gets ``None`` rather than blocking — it
    short-circuits as a "skipped" run. Two duplicate enqueues (which can
    happen when ``mark_success`` retries, or when an admin manually
    triggers regenerate while the auto path is in flight) thus produce
    exactly one LLM call.

    Returning None is a legitimate skip signal (the caller treats it as
    "nothing to do"), distinct from a missing row which would also return
    None — both outcomes are equivalent from this task's perspective.
    """
    stmt = (
        select(Source)
        .where(Source.id == source_id)
        .where(Source.name_status == "pending_ai")
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _build_profiler_factory() -> SourceProfilerFactory:
    """Resolve the SourceProfilerFactory from the class-level container.

    ``Container`` declares its providers at the class level — every
    ``Container.xxx()`` call returns the *same* singleton instance because
    the providers are class attributes, not instance state. Constructing a
    fresh ``Container()`` here would shadow that with a per-call container
    whose Singleton providers would build *new* AIModelResolver and Langfuse
    clients on every Celery task invocation, opening duplicate HTTP
    connections and bypassing pool reuse.
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_profiler_factory()


async def _generate_name_and_description(profile: Any) -> tuple[str, str]:
    """Call :class:`SourceNamingService` to produce a name + description
    from the structured profile. The naming service handles the LLM call,
    Langfuse tracing, structured-output validation, and template assembly.
    """
    from src.core.container import Container  # noqa: PLC0415

    # Class-level access — same singleton the FastAPI process uses; see
    # _build_profiler_factory for why this matters.
    naming_service = Container.source_naming_service()
    naming = await naming_service.name_from_profile(profile)
    return naming.name, naming.description


async def _persist_ai_naming(
    session: AsyncSession,
    *,
    source: Source,
    ai_name: str,
    ai_description: str,
) -> None:
    """Atomic-within-transaction write of the AI's name + description.

    Audits the description write in ``source_description_history`` so the
    admin UI can show "AI wrote this on <date>" alongside any prior
    user-authored description.
    """
    # Snapshot the previous description for the audit row.
    prior_description = source.description

    await session.execute(
        update(Source)
        .where(Source.id == source.id)
        .values(
            name=ai_name,
            description=ai_description,
            name_status="ai_set",
            description_status="ai_set",
        )
    )

    # ``SourceDescriptionHistory.description`` records the value that was
    # REPLACED — the old description. ``replaced_by=None`` means the AI /
    # system did it (the column is nullable so admins-only rows can stay
    # populated). We only insert a row if there was a non-null prior
    # description; otherwise there's nothing to audit.
    if prior_description:
        history_row = SourceDescriptionHistory(
            source_id=source.id,
            description=prior_description,
            replaced_by=None,
        )
        session.add(history_row)
