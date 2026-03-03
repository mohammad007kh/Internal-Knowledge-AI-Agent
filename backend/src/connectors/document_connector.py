"""Document connector — validates and extracts text from uploaded files.

Supports ``.pdf`` and ``.docx`` only.  Actual text extraction is delegated
to module-level stub helpers so tests can patch them without importing any
heavy third-party library.
"""
from __future__ import annotations

from pathlib import Path

from src.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Supported file types
# ---------------------------------------------------------------------------

SUPPORTED: frozenset[str] = frozenset({".pdf", ".docx"})


# ---------------------------------------------------------------------------
# Private extraction stubs (patch targets in tests)
# ---------------------------------------------------------------------------

async def _extract_text_from_pdf(content: bytes) -> str:  # pragma: no cover
    """Stub: extract text from *content* bytes of a PDF file.

    Replace with a real implementation (e.g. *pdfminer*, *pypdf*) when
    the dependency is available.  Returns an empty string by default.
    """
    return ""


async def _extract_text_from_docx(content: bytes) -> str:  # pragma: no cover
    """Stub: extract text from *content* bytes of a DOCX file.

    Replace with a real implementation (e.g. *python-docx*) when the
    dependency is available.  Returns an empty string by default.
    """
    return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class DocumentConnector:
    """Validates and extracts plain text from user-uploaded documents.

    This class is intentionally **not** a subclass of
    :class:`~src.connectors.base.BaseConnector` because it operates on
    in-memory byte buffers rather than persistent connections.

    Args:
        max_size_mb: Maximum allowed file size in megabytes (default: 50).
    """

    def __init__(self, max_size_mb: int = 50) -> None:
        self._max_bytes: int = max_size_mb * 1024 * 1024

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate_file(self, filename: str, size_bytes: int) -> None:
        """Validate that *filename* has a supported extension and is within
        the size limit.

        Args:
            filename: Original file name (used to infer extension).
            size_bytes: Size of the file in bytes.

        Raises:
            :exc:`~src.core.exceptions.ValidationError`: When the extension
                is not supported or the file exceeds the size limit.
        """
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED:
            raise ValidationError(
                f"Unsupported file type: '{ext}'. "
                f"Allowed: {sorted(SUPPORTED)}"
            )
        if size_bytes > self._max_bytes:
            max_mb = self._max_bytes // (1024 * 1024)
            raise ValidationError(
                f"File too large: {size_bytes} bytes "
                f"(limit is {max_mb} MB)"
            )

    async def extract_text(self, filename: str, content: bytes) -> str:
        """Extract plain text from *content* according to *filename*'s extension.

        Args:
            filename: Original file name (used to dispatch to the correct
                extraction helper).
            content: Raw file bytes.

        Returns:
            Extracted text as a plain string.

        Raises:
            :exc:`~src.core.exceptions.ValidationError`: When the extension
                is not supported.
        """
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            return await _extract_text_from_pdf(content)
        if ext == ".docx":
            return await _extract_text_from_docx(content)
        raise ValidationError(
            f"Unsupported file type for extraction: '{ext}'. "
            f"Allowed: {sorted(SUPPORTED)}"
        )
