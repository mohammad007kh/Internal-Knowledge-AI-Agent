"""Redis-backed cooperative cancellation flags for sync tasks (U16).

The flag is **source-scoped**, not job-scoped. Each ``trigger_sync`` call
produces two SyncJob rows (one created by the API endpoint and a second one
created inside the Celery task), so a job-id-keyed flag would miss the
in-flight task's row. Source-id is the only stable identifier shared between
the cancel endpoint and the running task.

Checkpoints in the sync / study tasks call :func:`is_sync_cancelled` between
safe boundaries. When the flag is set, they exit cleanly — committing any
work that already landed and flipping their SyncJob row to
``status='cancelled'``.

The flag carries a short TTL so a flag set for a job that never honoured it
(broker outage, worker crash) does not bleed into a *subsequent* sync of the
same source. The TTL is generous enough to cover the longest realistic
checkpoint gap (the bulk-embed call on a large source) — see
:data:`CANCEL_FLAG_TTL_SECONDS`.

The FastAPI process initialises the module-level :data:`redis_client` via
the app lifespan. The Celery worker does NOT go through that lifespan, so
the helpers in this module fall back to opening a per-call Redis connection
bound to the current event loop when :data:`redis_client` is ``None``. This
keeps the cancel signal usable from both processes without the worker
having to plumb its own Redis singleton.
"""

from __future__ import annotations

import logging
import uuid

import redis.asyncio as aioredis
from redis.asyncio import Redis

from src.core import redis as redis_module
from src.core.config import settings

logger = logging.getLogger(__name__)


# Generous upper bound — large embedding batches can take several minutes
# during which no checkpoint runs. After this expiry a stale flag self-clears
# so the next sync starts fresh even if the previous task crashed without
# observing it.
CANCEL_FLAG_TTL_SECONDS: int = 3600


def _key(source_id: uuid.UUID | str) -> str:
    """Return the Redis key for *source_id*'s cancel flag."""
    return f"sync:cancel:source:{source_id}"


async def _resolve_client() -> tuple[Redis, bool]:
    """Return ``(client, owned)``.

    ``owned=True`` means the caller MUST close the client when done — the
    fallback path opens a one-shot connection inside the current event loop
    when the module-level singleton is unset (Celery worker process).
    ``owned=False`` means the FastAPI lifespan-managed singleton is in play
    and the caller must leave it open for the next request.
    """
    if redis_module.redis_client is not None:
        return redis_module.redis_client, False
    client = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    return client, True


async def _close_if_owned(client: Redis, owned: bool) -> None:
    if not owned:
        return
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001 — best-effort
        logger.debug("sync.cancel: error closing one-shot Redis client", exc_info=True)


async def set_sync_cancelled(source_id: uuid.UUID | str) -> bool:
    """Set the cancel flag for *source_id*.

    Returns ``True`` when the flag was written, ``False`` when Redis is
    unavailable. Callers should treat a ``False`` return as a non-fatal
    warning — the queued-task revoke + the DB-row flip already provide a
    cancellation signal; the Redis flag is the running-task signal only.
    """
    client, owned = await _resolve_client()
    try:
        await client.set(_key(source_id), "1", ex=CANCEL_FLAG_TTL_SECONDS)
        return True
    except Exception:  # noqa: BLE001
        logger.warning(
            "sync.cancel: failed to set Redis flag for source_id=%s",
            source_id,
            exc_info=True,
        )
        return False
    finally:
        await _close_if_owned(client, owned)


async def is_sync_cancelled(source_id: uuid.UUID | str) -> bool:
    """Return ``True`` iff the cancel flag is set for *source_id*.

    Safe to call from inside a Celery task — opens no DB session. Returns
    ``False`` when Redis is unavailable (fail-open: a missing Redis means
    cancellation cannot be requested, so we let the sync continue).
    """
    client, owned = await _resolve_client()
    try:
        raw = await client.get(_key(source_id))
        return raw is not None
    except Exception:  # noqa: BLE001
        logger.warning(
            "sync.cancel: failed to read Redis flag for source_id=%s",
            source_id,
            exc_info=True,
        )
        return False
    finally:
        await _close_if_owned(client, owned)


async def clear_sync_cancelled(source_id: uuid.UUID | str) -> None:
    """Best-effort clear. Called by the task on a clean cancel exit so the
    flag does not leak into the next sync."""
    client, owned = await _resolve_client()
    try:
        await client.delete(_key(source_id))
    except Exception:  # noqa: BLE001
        logger.warning(
            "sync.cancel: failed to clear Redis flag for source_id=%s",
            source_id,
            exc_info=True,
        )
    finally:
        await _close_if_owned(client, owned)
