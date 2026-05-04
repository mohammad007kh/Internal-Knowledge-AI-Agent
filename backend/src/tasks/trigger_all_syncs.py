"""Beat-scheduled task: fan out sync_source.delay() for every active source (T-065)."""
from __future__ import annotations

import asyncio
import logging

from src.connectors.factory import ConnectorFactory
from src.core.config import settings
from src.core.database import task_session
from src.repositories.source_repository import SourceRepository
from src.services.source_service import SourceService
from src.tasks import celery_app
from src.tasks.sync_source import sync_source

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.trigger_all_syncs")  # type: ignore[untyped-decorator]
def trigger_all_syncs() -> dict[str, int]:
    """Dispatch one sync_source task per active source.

    Returns
    -------
    dict[str, int]
        ``{"dispatched": <count>}`` — number of sync_source tasks enqueued.
    """
    return asyncio.run(_trigger_async())


async def _trigger_async() -> dict[str, int]:
    """Fetch active sources and fan out ``sync_source`` tasks.

    Builds a per-task SourceService bound to a per-task engine so the
    asyncpg connections used here don't leak across event loops — see
    ``src.core.database.task_session`` for the rationale.
    """
    # Per-task engine — connections created here die with this loop.
    async with task_session() as session:
        source_service = SourceService(
            source_repo=SourceRepository(session),
            settings=settings,
            connector_factory=ConnectorFactory(),
        )
        sources, _ = await source_service.list_all_active_sources()

    dispatched = 0
    for src in sources:
        sync_source.delay(str(src.id))
        dispatched += 1
        logger.debug("Dispatched sync_source for source_id=%s", src.id)

    logger.info("trigger_all_syncs dispatched %d tasks", dispatched)
    return {"dispatched": dispatched}
