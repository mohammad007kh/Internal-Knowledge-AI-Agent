"""Embedding service wrapping OpenAI text-embedding-3-small."""
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

EMBEDDING_DIM:   Final[int] = 1536
EMBEDDING_MODEL: Final[str] = "text-embedding-3-small"
BATCH_SIZE:      Final[int] = 100

_RETRYABLE = (APIStatusError, APIConnectionError, TimeoutError)


class EmbeddingService:
    """Generates dense vectors using OpenAI *text-embedding-3-small*."""

    def __init__(self, openai_api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=openai_api_key)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _validate(embedding: list[float]) -> None:
        if len(embedding) != EMBEDDING_DIM:
            raise EmbeddingDimensionError(EMBEDDING_DIM, len(embedding))

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
                    model=EMBEDDING_MODEL,
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
        """
        Embed an arbitrary number of texts.

        Splits *texts* into batches of :data:`BATCH_SIZE`, processes them
        concurrently, then rejoins in original order.

        Parameters
        ----------
        texts:
            Input strings.  Empty list returns ``[]``.

        Returns
        -------
        list[list[float]]
            Parallel list of 1536-dimensional embedding vectors.
        """
        if not texts:
            return []

        batches = [
            texts[i : i + BATCH_SIZE]
            for i in range(0, len(texts), BATCH_SIZE)
        ]

        results: list[list[list[float]]] = await asyncio.gather(
            *[self._embed_batch(batch) for batch in batches]
        )

        # Flatten while preserving order
        return [vec for batch_vecs in results for vec in batch_vecs]

    async def embed_single(self, text: str) -> list[float]:
        """
        Convenience wrapper for embedding a single text.

        Returns
        -------
        list[float]
            1536-dimensional embedding vector.
        """
        vectors = await self.embed_texts([text])
        return vectors[0]
