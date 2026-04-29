"""AIModelResolver — singleton with TTL cache for stage → AIModelClient lookups.

Pipeline nodes call ``await resolver.resolve("synthesizer")`` (or any
other seeded stage slot) at node entry to obtain an immutable
:class:`AIModelClient` carrying the ``AsyncOpenAI`` HTTP pool plus the
resolved temperature / max_tokens / capabilities for the stage.

The resolver:

* caches the ``stage → AIModelClient`` mapping for 60 s (configurable);
* caches the underlying ``AsyncOpenAI`` clients keyed by
  ``(provider, base_url, api_key_hash)`` so HTTP pools are reused;
* exposes :meth:`invalidate` for surgical refresh from the admin endpoint.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.crypto import decrypt
from src.models.ai_model import AIModel
from src.models.llm_configuration import LLMConfiguration
from src.repositories.ai_model_repository import AIModelRepository
from src.repositories.llm_config_repository import LLMConfigRepository

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class AIModelClient:
    """Immutable resolved client carrying everything a node needs."""

    ai_model_id: uuid.UUID
    provider: str
    model_id: str
    temperature: float
    max_tokens: int
    custom_prompt: str | None
    capabilities: dict[str, Any]
    http_client: AsyncOpenAI


class AIModelResolver:
    """Resolves a pipeline stage to an :class:`AIModelClient`, with TTL cache."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession]
        | Callable[[], AsyncSession],
        ttl_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._stage_cache: dict[str, tuple[float, AIModelClient]] = {}
        # Underlying HTTP clients keyed by (provider, base_url, api_key_hash).
        self._http_clients: dict[tuple[str, str, str], AsyncOpenAI] = {}
        # Lazy-created so the lock binds to whichever event loop is actually
        # running when ``resolve`` is first awaited.  ``asyncio.Lock()`` in
        # ``__init__`` would bind to the loop that constructed the DI
        # singleton, which fails inside pytest-asyncio function-scoped loops.
        self._lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def resolve(self, stage: str) -> AIModelClient:
        """Return a cached or freshly built :class:`AIModelClient` for *stage*."""
        cached = self._stage_cache.get(stage)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]

        async with self._get_lock():
            cached = self._stage_cache.get(stage)
            if cached is not None and (time.monotonic() - cached[0]) < self._ttl:
                return cached[1]
            client = await self._build_for_stage(stage)
            self._stage_cache[stage] = (time.monotonic(), client)
            return client

    def invalidate(self, stage: str | None = None) -> None:
        """Drop cached entries.  ``stage=None`` clears every stage."""
        if stage is None:
            self._stage_cache.clear()
        else:
            self._stage_cache.pop(stage, None)

    async def aclose(self) -> None:
        """Close every pooled :class:`AsyncOpenAI` HTTP client.

        Wired into the FastAPI lifespan shutdown — see ``src/main.py``.
        Closing the OpenAI clients in turn closes their underlying httpx
        AsyncClient pools, releasing sockets cleanly on shutdown.
        """
        for client in list(self._http_clients.values()):
            try:
                await client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.warning(
                    "AIModelResolver.aclose: client.close() failed",
                    exc_info=True,
                )
        self._http_clients.clear()
        self._stage_cache.clear()

    # ------------------------------------------------------------------ #
    # Internal builders                                                   #
    # ------------------------------------------------------------------ #

    async def _build_for_stage(self, stage: str) -> AIModelClient:
        async with self._open_session() as session:
            llm_repo = LLMConfigRepository(session)
            ai_repo = AIModelRepository(session)
            llm_row = await llm_repo.get_by_slot(stage)
            ai_row: AIModel | None = None
            if llm_row is not None and llm_row.ai_model_id is not None:
                ai_row = await ai_repo.get_by_id(llm_row.ai_model_id)
            if ai_row is None:
                # Fallback: if no v2 link exists, try to find any active model.
                ai_row = await self._fallback_active(ai_repo)
            if ai_row is None:
                raise RuntimeError(
                    f"No AIModel configured for stage {stage!r}. "
                    "Register one under /admin/ai-models and link via /admin/llm-settings."
                )
            return self._materialise(stage, llm_row, ai_row)

    @staticmethod
    async def _fallback_active(ai_repo: AIModelRepository) -> AIModel | None:
        rows, _ = await ai_repo.search(active=True, limit=1, offset=0)
        return rows[0] if rows else None

    def _materialise(
        self,
        stage: str,
        llm_row: LLMConfiguration | None,
        ai_row: AIModel,
    ) -> AIModelClient:
        api_key = self._decrypt_or_empty(ai_row.api_key_encrypted)
        http_client = self._http_client_for(
            provider=ai_row.provider,
            base_url=ai_row.base_url,
            api_key=api_key,
        )
        temperature = (
            llm_row.temperature
            if llm_row is not None and llm_row.temperature is not None
            else ai_row.default_temperature
        )
        max_tokens = (
            llm_row.max_tokens
            if llm_row is not None and llm_row.max_tokens
            else ai_row.default_max_tokens
        )
        custom_prompt = llm_row.custom_prompt if llm_row is not None else None
        return AIModelClient(
            ai_model_id=ai_row.id,
            provider=ai_row.provider,
            model_id=ai_row.model_id,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            custom_prompt=custom_prompt,
            capabilities=dict(ai_row.capabilities or {}),
            http_client=http_client,
        )

    @staticmethod
    def _decrypt_or_empty(blob: bytes | None) -> str:
        if not blob:
            return ""
        try:
            return decrypt(blob)
        except Exception:  # noqa: BLE001 - best-effort fallback
            logger.warning(
                "AIModelResolver: failed to decrypt api_key — using empty key"
            )
            return ""

    def _http_client_for(
        self,
        *,
        provider: str,
        base_url: str | None,
        api_key: str,
    ) -> AsyncOpenAI:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest() if api_key else "anon"
        cache_key = (provider, base_url or "", digest)
        client = self._http_clients.get(cache_key)
        if client is not None:
            return client
        kwargs: dict[str, str] = {"api_key": api_key or "missing"}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        self._http_clients[cache_key] = client
        return client

    # ------------------------------------------------------------------ #
    # Session helper                                                      #
    # ------------------------------------------------------------------ #

    def _open_session(self) -> Any:
        """Return an async-context-manager yielding an AsyncSession."""
        sf = self._session_factory
        # ``async_sessionmaker`` instances are themselves callable and return
        # an AsyncSession (an async context manager); plain factories work
        # the same way.
        return sf()
