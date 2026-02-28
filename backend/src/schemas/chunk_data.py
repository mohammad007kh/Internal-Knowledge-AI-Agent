"""In-memory data contract for chunked text before DB persistence."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChunkData:
    """Represents a single text chunk produced by ChunkingService."""

    text: str
    chunk_index: int
    metadata: dict[str, object] = field(default_factory=dict)
