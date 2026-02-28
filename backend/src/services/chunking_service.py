"""Text chunking service using LangChain RecursiveCharacterTextSplitter."""
from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.schemas.chunk_data import ChunkData

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


class ChunkingService:
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

    @staticmethod
    def _preprocess(text: str) -> str:
        text = _WHITESPACE_RE.sub(" ", text)
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text.strip()

    def chunk_text(
        self,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> list[ChunkData]:
        base_meta = metadata or {}
        cleaned = self._preprocess(text)
        if not cleaned:
            return []
        raw_chunks: list[str] = self._splitter.split_text(cleaned)
        return [
            ChunkData(
                text=chunk,
                chunk_index=idx,
                metadata={**base_meta, "chunk_index": idx},
            )
            for idx, chunk in enumerate(raw_chunks)
        ]
