"""Unit tests for EmbeddingService."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import EmbeddingDimensionError
from src.services.embedding_service import EMBEDDING_DIM, EmbeddingService


def _make_response(texts: list[str]) -> MagicMock:
    """Build a mock embeddings response with correct-dimension vectors."""
    mock = MagicMock()
    mock.data = [
        SimpleNamespace(index=i, embedding=[0.1] * EMBEDDING_DIM)
        for i in range(len(texts))
    ]
    return mock


@pytest.fixture
def svc() -> EmbeddingService:
    return EmbeddingService(openai_api_key="test-key")


async def test_empty_returns_empty(svc: EmbeddingService) -> None:
    result = await svc.embed_texts([])
    assert result == []


async def test_single_text(svc: EmbeddingService) -> None:
    response = _make_response(["hello"])
    with patch.object(
        svc._client.embeddings, "create", new=AsyncMock(return_value=response)
    ):
        result = await svc.embed_texts(["hello"])

    assert len(result) == 1
    assert len(result[0]) == EMBEDDING_DIM


async def test_batching(svc: EmbeddingService) -> None:
    texts = [f"text_{i}" for i in range(250)]
    call_sizes: list[int] = []

    async def fake_create(**kwargs: object) -> MagicMock:
        batch = kwargs["input"]
        call_sizes.append(len(batch))  # type: ignore[arg-type]
        return _make_response(batch)  # type: ignore[arg-type]

    with patch.object(svc._client.embeddings, "create", new=fake_create):
        result = await svc.embed_texts(texts)

    assert len(result) == 250
    assert sorted(call_sizes) == [50, 100, 100]


async def test_dimension_validation_error(svc: EmbeddingService) -> None:
    bad_response = MagicMock()
    bad_response.data = [SimpleNamespace(index=0, embedding=[0.1] * 10)]

    with patch.object(
        svc._client.embeddings, "create", new=AsyncMock(return_value=bad_response)
    ):
        with pytest.raises(EmbeddingDimensionError):
            await svc.embed_texts(["hello"])


async def test_embed_single_delegate(svc: EmbeddingService) -> None:
    mock_embed = AsyncMock(return_value=[[0.1] * EMBEDDING_DIM])
    with patch.object(svc, "embed_texts", new=mock_embed):
        result = await svc.embed_single("hello")

    mock_embed.assert_called_once_with(["hello"])
    assert len(result) == EMBEDDING_DIM
