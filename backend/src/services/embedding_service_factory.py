"""EmbeddingServiceFactory — replaces the module-level embedding singleton.

v1 invariant: there is exactly one active embedder per deployment, so
``for_active``, ``for_source``, and ``for_embedder`` all converge on the
same underlying record under normal conditions.  The factory still keys
its cache by ``embedder_id`` so the v1.1 transition (per-source heterogeneous
embedders) is a one-line change in :meth:`for_source`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.crypto import decrypt
from src.models.embedder import Embedder
from src.repositories.embedder_repository import EmbedderRepository
from src.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class EmbeddingServiceFactory:
    """Returns :class:`EmbeddingService` instances pinned to admin-managed embedders."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession]
        | Callable[[], AsyncSession],
        ttl_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        # embedder_id → (timestamp, EmbeddingService)
        self._cache: dict[uuid.UUID, tuple[float, EmbeddingService]] = {}
        # Cached "active embedder id" lookup so we don't roundtrip per call.
        self._active_id: tuple[float, uuid.UUID] | None = None
        # Lazy-created so the lock binds to the actual running event loop;
        # creating it in ``__init__`` binds it to the loop that built the DI
        # singleton, which fails inside pytest-asyncio function-scoped loops.
        self._lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def for_active(self) -> tuple[EmbeddingService, uuid.UUID]:
        """Return the service AND the active embedder id.

        Returning the id alongside the service avoids a second DB roundtrip
        from callers (retrieve node, sync_source task) that need to stamp
        ``embedder_id`` onto chunks or push it through a defensive filter.
        """
        embedder_id = await self._resolve_active_id()
        service = await self.for_embedder(embedder_id)
        return service, embedder_id

    async def for_source(
        self, source_id: uuid.UUID
    ) -> tuple[EmbeddingService, uuid.UUID]:
        """v1: one active embedder deployment-wide → ignore *source_id*.

        Kept as a distinct entry point so v1.1 can switch to a per-source
        lookup without touching every caller.
        """
        del source_id  # placeholder, see docstring
        return await self.for_active()

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def for_embedder(self, embedder_id: uuid.UUID) -> EmbeddingService:
        cached = self._cache.get(embedder_id)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]

        async with self._get_lock():
            cached = self._cache.get(embedder_id)
            if cached is not None and (time.monotonic() - cached[0]) < self._ttl:
                return cached[1]
            service = await self._build(embedder_id)
            self._cache[embedder_id] = (time.monotonic(), service)
            return service

    def invalidate(self, embedder_id: uuid.UUID | None = None) -> None:
        if embedder_id is None:
            self._cache.clear()
            self._active_id = None
        else:
            self._cache.pop(embedder_id, None)
            if self._active_id is not None and self._active_id[1] == embedder_id:
                self._active_id = None

    async def aclose(self) -> None:
        """Close pooled httpx clients held by every cached EmbeddingService.

        Wired into the FastAPI lifespan shutdown — see ``src/main.py``.
        ``EmbeddingService`` keeps an ``AsyncOpenAI`` client (which owns an
        underlying httpx pool) at ``service._client``; closing it releases
        sockets cleanly on shutdown.
        """
        for _ts, service in list(self._cache.values()):
            client = getattr(service, "_client", None)
            if client is None:
                continue
            try:
                await client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.warning(
                    "EmbeddingServiceFactory.aclose: client.close() failed",
                    exc_info=True,
                )
        self._cache.clear()
        self._active_id = None

    # ------------------------------------------------------------------ #
    # Internal builders                                                   #
    # ------------------------------------------------------------------ #

    async def _resolve_active_id(self) -> uuid.UUID:
        cached = self._active_id
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]
        async with self._get_lock():
            cached = self._active_id
            if cached is not None and (time.monotonic() - cached[0]) < self._ttl:
                return cached[1]
            async with self._open_session() as session:
                repo = EmbedderRepository(session)
                row = await repo.get_active()
            if row is None:
                raise RuntimeError(
                    "No active Embedder configured. "
                    "Register one under /admin/embedders and activate it."
                )
            self._active_id = (time.monotonic(), row.id)
            return row.id

    async def _build(self, embedder_id: uuid.UUID) -> EmbeddingService:
        async with self._open_session() as session:
            repo = EmbedderRepository(session)
            row = await repo.get_by_id(embedder_id)
        if row is None:
            raise RuntimeError(f"Embedder {embedder_id} not found")
        return self._materialise(row)

    @staticmethod
    def _materialise(row: Embedder) -> EmbeddingService:
        api_key = ""
        if row.api_key_encrypted:
            try:
                api_key = decrypt(row.api_key_encrypted)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "EmbeddingServiceFactory: failed to decrypt api_key for "
                    "embedder=%s — using empty key",
                    row.id,
                )
        return EmbeddingService.from_record(
            api_key=api_key,
            model_id=row.model_id,
            dimensions=row.dimensions,
            base_url=row.base_url,
        )

    # ------------------------------------------------------------------ #
    # Session helper                                                      #
    # ------------------------------------------------------------------ #

    def _open_session(self) -> Any:
        sf = self._session_factory
        return sf()
