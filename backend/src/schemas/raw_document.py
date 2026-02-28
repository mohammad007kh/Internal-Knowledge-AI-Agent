"""Intermediate representation returned by connector.fetch_documents() (T-064)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RawDocument:
    """
    Plain-data carrier produced by a connector and consumed by the
    fetch → chunk → embed → persist pipeline inside the Celery task.

    Attributes:
        title:        Human-readable document title (used as metadata).
        content:      Full plain-text content to be chunked and embedded.
        url:          Canonical URL / path of the source document.
        content_hash: Hex digest (e.g. SHA-256) of ``content``; empty string
                      when the connector does not produce one.
        metadata:     Arbitrary extra key/value pairs forwarded as-is into
                      the ``Document.metadata_`` JSON column.
    """

    title: str
    content: str
    url: str = ""
    content_hash: str = ""
    metadata: dict = field(default_factory=dict)
