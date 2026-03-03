# T-063 â€” Embedding Service

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· dependency-injector
openai>=1.0 Â· tenacity
EMBEDDING_DIM = 1536 (text-embedding-3-small)
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Implement `EmbeddingService` that wraps the OpenAI `text-embedding-3-small` model,
batches large inputs, retries transient failures, and validates output dimensions.

---

## Acceptance Criteria

- [ ] Uses `text-embedding-3-small`; output dim = 1536
- [ ] Batches `embed_texts` calls at 100 texts per API request
- [ ] `tenacity` retry: max 3 attempts, `wait_exponential(multiplier=1, min=1, max=10)`
- [ ] Raises `EmbeddingDimensionError(ValueError)` when a returned embedding â‰  1536 floats
- [ ] Registered as **Singleton** in DI container (shares one `AsyncOpenAI` client)

---

## 1  Error Types â€” `app/core/exceptions.py` patch

```python
# -- append to existing exceptions.py --

class EmbeddingDimensionError(ValueError):
    """Raised when the embedded vector length != EMBEDDING_DIM."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Expected embedding dimension {expected}, got {actual}"
        )
        self.expected = expected
        self.actual = actual
```

---

## 2  Service â€” `app/services/embedding_service.py`

```python
# app/services/embedding_service.py
"""OpenAI text embedding service with batching and retry."""
from __future__ import annotations

import asyncio
import logging
from typing import Final

from openai import AsyncOpenAI, APIStatusError, APIConnectionError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import EmbeddingDimensionError

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
        """Embed a single batch of â‰¤ BATCH_SIZE texts with retry."""
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
        vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
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
```

---

## 3  DI Container â€” `app/containers.py` patch

```python
# -- inside ApplicationContainer -- add after chunking_service:

    # â”€â”€ Embeddings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    embedding_service: providers.Singleton[EmbeddingService] = providers.Singleton(
        EmbeddingService,
        openai_api_key=config.provided.openai.api_key,
    )
```

Add import at top of `containers.py`:

```python
from app.services.embedding_service import EmbeddingService
```

---

## 4  Settings â€” `app/core/config.py` patch

Add `openai` section to `AppConfig` / `pydantic_settings` model:

```python
class OpenAISettings(BaseModel):
    api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    # model and dim are constants â€” not in settings

class AppConfig(BaseSettings):
    # ... existing fields ...
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
```

`docker-compose.yml` â€” backend service `environment`:
```yaml
- OPENAI_API_KEY=${OPENAI_API_KEY}
```

---

## 5  Dependencies â€” `requirements.txt` additions

```
openai>=1.35.0
tenacity>=8.3.0
```

---

## 6  Unit Tests â€” `tests/unit/test_embedding_service.py`

```python
# tests/unit/test_embedding_service.py
"""Unit tests for EmbeddingService (mocked OpenAI client)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest

from app.services.embedding_service import EmbeddingService, EMBEDDING_DIM
from app.core.exceptions import EmbeddingDimensionError


def _make_response(texts: list[str]) -> MagicMock:
    """Build a mock OpenAI embeddings response."""
    response = MagicMock()
    response.data = [
        SimpleNamespace(index=i, embedding=[0.1] * EMBEDDING_DIM)
        for i in range(len(texts))
    ]
    return response


@pytest.fixture
def svc() -> EmbeddingService:
    return EmbeddingService(openai_api_key="test-key")


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_empty_returns_empty(self, svc):
        assert await svc.embed_texts([]) == []

    @pytest.mark.asyncio
    async def test_single_text(self, svc):
        with patch.object(
            svc._client.embeddings, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = _make_response(["hello"])
            result = await svc.embed_texts(["hello"])
        assert len(result) == 1
        assert len(result[0]) == EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_batching(self, svc):
        """250 texts â†’ 3 API calls (100 + 100 + 50)."""
        texts = ["t"] * 250
        calls: list[int] = []

        async def _fake_create(**kwargs):
            batch = kwargs["input"]
            calls.append(len(batch))
            return _make_response(batch)

        with patch.object(svc._client.embeddings, "create", side_effect=_fake_create):
            result = await svc.embed_texts(texts)

        assert sorted(calls) == [50, 100, 100]
        assert len(result) == 250

    @pytest.mark.asyncio
    async def test_dimension_validation_error(self, svc):
        bad_response = MagicMock()
        bad_response.data = [SimpleNamespace(index=0, embedding=[0.1] * 10)]

        with patch.object(
            svc._client.embeddings, "create", new_callable=AsyncMock,
            return_value=bad_response,
        ):
            with pytest.raises(EmbeddingDimensionError):
                await svc.embed_texts(["bad"])

    @pytest.mark.asyncio
    async def test_embed_single_delegate(self, svc):
        with patch.object(svc, "embed_texts", new_callable=AsyncMock) as m:
            m.return_value = [[0.2] * EMBEDDING_DIM]
            vec = await svc.embed_single("hello")
        m.assert_called_once_with(["hello"])
        assert len(vec) == EMBEDDING_DIM
```

---

## 7  Verification Checklist

```bash
pytest tests/unit/test_embedding_service.py -v
# Expected: 5 tests passing

python -c "
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from types import SimpleNamespace
from app.services.embedding_service import EmbeddingService, EMBEDDING_DIM

svc = EmbeddingService('test-key')
resp = MagicMock()
resp.data = [SimpleNamespace(index=0, embedding=[0.1]*EMBEDDING_DIM)]
with patch.object(svc._client.embeddings, 'create', new_callable=AsyncMock, return_value=resp):
    result = asyncio.run(svc.embed_single('test'))
assert len(result) == 1536
print('embedding_service OK')
"
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-031 â€” vector embeddings | `embed_texts()` â†’ 1536-dim vectors |
| FR-031 â€” batch efficiency | `BATCH_SIZE=100`, concurrent `asyncio.gather` |
| FR-031 â€” resilience | tenacity 3-attempt exponential backoff |
