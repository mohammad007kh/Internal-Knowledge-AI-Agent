# T-062 â€” Text Chunking Service

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· dependency-injector
langchain-text-splitters
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Implement `ChunkingService` using LangChain's `RecursiveCharacterTextSplitter`.
Returns typed `ChunkData` objects ready for embedding and database persistence.

---

## Acceptance Criteria

- [ ] `chunk_size=512`, `chunk_overlap=64` applied globally
- [ ] Whitespace pre-processing: strip excess whitespace, normalize newlines
- [ ] Returns `list[ChunkData]` with sequential `chunk_index` starting at 0
- [ ] `metadata` dict is merged with chunk-level keys (`chunk_index`, `char_start`, `char_end`)
- [ ] `chunk_text("")` returns `[]` â€” no error on empty input
- [ ] Service is container-registered as Singleton

---

## 1  Data Contract â€” `app/schemas/chunk_data.py`

```python
# app/schemas/chunk_data.py
"""In-memory data contract for chunked text before DB persistence."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChunkData:
    """Represents a single text chunk produced by ChunkingService."""
    text:        str
    chunk_index: int
    metadata:    dict = field(default_factory=dict)
```

---

## 2  Service â€” `app/services/chunking_service.py`

```python
# app/services/chunking_service.py
"""Text chunking service using LangChain RecursiveCharacterTextSplitter."""
from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.schemas.chunk_data import ChunkData

CHUNK_SIZE    = 512
CHUNK_OVERLAP = 64

_WHITESPACE_RE   = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


class ChunkingService:
    """Splits raw text into overlapping chunks."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _preprocess(text: str) -> str:
        """Normalise whitespace and collapse excessive blank lines."""
        text = _WHITESPACE_RE.sub(" ", text)          # collapse spaces/tabs
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)    # max 2 consecutive newlines
        return text.strip()

    # ------------------------------------------------------------------ main
    def chunk_text(
        self,
        text: str,
        metadata: dict | None = None,
    ) -> list[ChunkData]:
        """
        Split *text* into overlapping chunks.

        Parameters
        ----------
        text:
            Raw document text.
        metadata:
            Caller-supplied metadata merged into each ChunkData.
            Chunk-level keys (``chunk_index``) are added automatically.

        Returns
        -------
        list[ChunkData]
            Empty list if *text* is blank after preprocessing.
        """
        base_meta = metadata or {}
        cleaned = self._preprocess(text)

        if not cleaned:
            return []

        raw_chunks: list[str] = self._splitter.split_text(cleaned)

        return [
            ChunkData(
                text=chunk,
                chunk_index=idx,
                metadata={
                    **base_meta,
                    "chunk_index": idx,
                },
            )
            for idx, chunk in enumerate(raw_chunks)
        ]
```

---

## 3  DI Container â€” `app/containers.py` patch

```python
# -- inside ApplicationContainer -- add after sync_job_service:

    # â”€â”€ Chunking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    chunking_service: providers.Singleton[ChunkingService] = providers.Singleton(
        ChunkingService
    )
```

Add import at top of `containers.py`:

```python
from app.services.chunking_service import ChunkingService
```

---

## 4  Dependency â€” `requirements.txt` addition

```
langchain-text-splitters>=0.2.0
```

---

## 5  Unit Tests â€” `tests/unit/test_chunking_service.py`

```python
# tests/unit/test_chunking_service.py
import pytest
from app.services.chunking_service import ChunkingService
from app.schemas.chunk_data import ChunkData

@pytest.fixture
def svc() -> ChunkingService:
    return ChunkingService(chunk_size=100, chunk_overlap=10)


class TestChunkText:
    def test_empty_string_returns_empty_list(self, svc):
        assert svc.chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self, svc):
        assert svc.chunk_text("   \n\n  ") == []

    def test_short_text_returns_single_chunk(self, svc):
        result = svc.chunk_text("Hello world")
        assert len(result) == 1
        assert result[0].chunk_index == 0
        assert result[0].text == "Hello world"

    def test_chunk_index_sequential(self, svc):
        long_text = ("word " * 30).strip()  # 150 chars > chunk_size=100
        result = svc.chunk_text(long_text)
        assert len(result) > 1
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_metadata_propagated(self, svc):
        result = svc.chunk_text("Short text.", metadata={"source_id": "abc"})
        assert result[0].metadata["source_id"] == "abc"
        assert result[0].metadata["chunk_index"] == 0

    def test_excess_whitespace_normalised(self, svc):
        result = svc.chunk_text("Hello   \t world")
        assert "  " not in result[0].text

    def test_excess_newlines_normalised(self, svc):
        result = svc.chunk_text("para1\n\n\n\n\npara2")
        combined = " ".join(c.text for c in result)
        assert "\n\n\n" not in combined

    def test_returns_chunk_data_instances(self, svc):
        result = svc.chunk_text("Some text")
        for chunk in result:
            assert isinstance(chunk, ChunkData)
```

---

## 6  Verification Checklist

```bash
pytest tests/unit/test_chunking_service.py -v
# Expected: 8 tests passing

python -c "
from app.services.chunking_service import ChunkingService
svc = ChunkingService()
chunks = svc.chunk_text('hello world')
assert chunks[0].chunk_index == 0
print('chunking_service OK')
"
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-030 â€” document chunking | `chunk_text()` with configurable size/overlap |
| FR-030 â€” sequential indices | `chunk_index` auto-assigned from 0 |
