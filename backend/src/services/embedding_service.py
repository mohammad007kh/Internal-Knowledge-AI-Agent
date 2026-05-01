"""Embedding service — wraps an OpenAI-compatible embeddings endpoint.

The legacy constructor ``EmbeddingService(openai_api_key=...)`` is preserved
for backward compatibility (uses ``text-embedding-3-small`` / 1536 dims).
The new constructor ``EmbeddingService.from_record(...)`` is invoked by
:class:`EmbeddingServiceFactory` and accepts a full embedder record so
non-default models / providers / dims can be served from the same code path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.exceptions import EmbeddingDimensionError

logger = logging.getLogger(__name__)

EMBEDDING_DIM: Final[int] = 1536
EMBEDDING_MODEL: Final[str] = "text-embedding-3-small"
BATCH_SIZE: Final[int] = 100

_RETRYABLE = (APIStatusError, APIConnectionError, TimeoutError)


class EmbeddingService:
    """Generates dense vectors via an OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        openai_api_key: str | None = None,
        *,
        api_key: str | None = None,
        model_id: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIM,
        base_url: str | None = None,
    ) -> None:
        """Construct an embedding service.

        Two call styles are supported for backward compatibility:

        * Legacy: ``EmbeddingService(openai_api_key="sk-…")`` —
          uses ``text-embedding-3-small`` and 1536 dims.
        * New: ``EmbeddingService(api_key=…, model_id=…, dimensions=…, base_url=…)``
          — invoked by :class:`EmbeddingServiceFactory`.
        """
        resolved_key = api_key if api_key is not None else openai_api_key or ""
        client_kwargs: dict[str, str] = {"api_key": resolved_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**client_kwargs)
        self._model = model_id
        self._dimensions = dimensions

    @classmethod
    def from_record(
        cls,
        *,
        api_key: str,
        model_id: str,
        dimensions: int,
        base_url: str | None = None,
    ) -> EmbeddingService:
        """Construct from an explicit embedder record (preferred)."""
        return cls(
            api_key=api_key,
            model_id=model_id,
            dimensions=dimensions,
            base_url=base_url,
        )

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_id(self) -> str:
        return self._model

    # ------------------------------------------------------------------ helpers
    def _validate(self, embedding: list[float]) -> None:
        if len(embedding) != self._dimensions:
            raise EmbeddingDimensionError(self._dimensions, len(embedding))

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed a single batch of ≤ BATCH_SIZE texts with retry."""
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
        vectors = [
            item.embedding
            for item in sorted(response.data, key=lambda x: x.index)
        ]
        for v in vectors:
            self._validate(v)
        return vectors

    # ------------------------------------------------------------------ public
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed an arbitrary number of texts."""
        if not texts:
            return []

        batches = [
            texts[i : i + BATCH_SIZE]
            for i in range(0, len(texts), BATCH_SIZE)
        ]

        results: list[list[list[float]]] = await asyncio.gather(
            *[self._embed_batch(batch) for batch in batches]
        )

        return [vec for batch_vecs in results for vec in batch_vecs]

    async def embed_single(self, text: str) -> list[float]:
        """Convenience wrapper for embedding a single text."""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def embed_query(self, text: str) -> list[float]:
        """Alias used by the retrieve node — see §6.3 of the design doc."""
        return await self.embed_single(text)
