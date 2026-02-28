"""Unit tests for ChunkingService."""
import pytest

from src.schemas.chunk_data import ChunkData
from src.services.chunking_service import ChunkingService


@pytest.fixture
def svc() -> ChunkingService:
    return ChunkingService(chunk_size=100, chunk_overlap=10)


class TestChunkText:
    def test_empty_string_returns_empty_list(self, svc: ChunkingService) -> None:
        assert svc.chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self, svc: ChunkingService) -> None:
        assert svc.chunk_text("   \n\n  ") == []

    def test_short_text_returns_single_chunk(self, svc: ChunkingService) -> None:
        result = svc.chunk_text("Hello world")
        assert len(result) == 1
        assert result[0].chunk_index == 0
        assert result[0].text == "Hello world"

    def test_chunk_index_sequential(self, svc: ChunkingService) -> None:
        long_text = "word " * 30  # 150 chars, exceeds chunk_size=100
        result = svc.chunk_text(long_text)
        assert len(result) > 1
        for idx, chunk in enumerate(result):
            assert chunk.chunk_index == idx

    def test_metadata_propagated(self, svc: ChunkingService) -> None:
        result = svc.chunk_text("Hello world", metadata={"source_id": "abc"})
        assert len(result) >= 1
        assert result[0].metadata["source_id"] == "abc"
        assert result[0].metadata["chunk_index"] == 0

    def test_excess_whitespace_normalised(self, svc: ChunkingService) -> None:
        result = svc.chunk_text("Hello   \t world")
        assert len(result) >= 1
        assert "  " not in result[0].text
        assert "\t" not in result[0].text

    def test_excess_newlines_normalised(self, svc: ChunkingService) -> None:
        result = svc.chunk_text("para1\n\n\n\n\npara2")
        combined = "".join(c.text for c in result)
        assert "\n\n\n" not in combined

    def test_returns_chunk_data_instances(self, svc: ChunkingService) -> None:
        result = svc.chunk_text("Hello world")
        assert len(result) >= 1
        for chunk in result:
            assert isinstance(chunk, ChunkData)
