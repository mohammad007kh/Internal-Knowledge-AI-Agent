"""File-upload connector — ingests binary objects stored in MinIO (T-047).

Supported file types
--------------------
* ``pdf``   — extracted via PyPDF2
* ``docx``  — extracted via python-docx
* ``xlsx``  — plain-text representation (CSV-like) via openpyxl
* ``csv``   — decoded as UTF-8 text
* ``txt``   — decoded as UTF-8 text
* ``md``    — decoded as UTF-8 Markdown text

Config keys expected in the connector ``config`` dict
------------------------------------------------------
* ``minio_bucket``  – MinIO bucket name
* ``object_key``    – full object path inside the bucket
* ``file_type``     – one of the supported extensions (case-insensitive)
* ``source_id``     – UUID string of the owning :class:`Source` record

Usage example::

    conn = FileUploadConnector(
        config={
            "minio_bucket": "knowledge-agent",
            "object_key":   "uploads/abc123/report.pdf",
            "file_type":    "pdf",
            "source_id":    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        }
    )
    await conn.connect()
    async for doc in conn.extract_documents():
        ...
    await conn.disconnect()
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.core.app_config import get_app_config
from src.models.enums import SourceType
from src.services.storage_service import StorageService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported file-type constants
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES: frozenset[str] = frozenset({"pdf", "docx", "xlsx", "csv", "txt", "md"})

_TEXT_TYPES: frozenset[str] = frozenset({"csv", "txt", "md"})


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


@register(SourceType.FILE_UPLOAD)
class FileUploadConnector(BaseConnector):
    """Ingest a single file that was previously uploaded to MinIO.

    The connector downloads the object bytes in :meth:`connect`, then
    :meth:`extract_documents` parses them into exactly **one**
    :class:`~src.connectors.base.Document` per call.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        self._bucket: str = config["minio_bucket"]
        self._object_key: str = config["object_key"]
        self._file_type: str = config["file_type"].lower().lstrip(".")
        self._source_id: str = str(config.get("source_id", ""))
        self._storage: StorageService = StorageService()
        self._raw_data: bytes | None = None

        if self._file_type not in _SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported file_type '{self._file_type}'. "
                f"Supported: {sorted(_SUPPORTED_TYPES)}"
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Download the object from MinIO and validate its size."""
        app_cfg = get_app_config()
        max_bytes: int = app_cfg.file_upload.max_size_bytes

        raw_data = await self._storage.download_bytes(
            bucket=self._bucket,
            object_key=self._object_key,
        )

        if len(raw_data) > max_bytes:
            raise ValueError(
                f"File size {len(raw_data):,} bytes exceeds the configured "
                f"maximum of {max_bytes:,} bytes "
                f"(object_key='{self._object_key}')."
            )

        self._raw_data = raw_data
        logger.info(
            "FileUploadConnector: downloaded %d bytes from %s/%s",
            len(raw_data),
            self._bucket,
            self._object_key,
        )

    async def disconnect(self) -> None:
        """Release the in-memory file bytes."""
        self._raw_data = None

    # ------------------------------------------------------------------
    # Document extraction
    # ------------------------------------------------------------------

    async def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
        """Yield a single :class:`Document` parsed from the uploaded file.

        Raises
        ------
        RuntimeError
            If :meth:`connect` has not been called first.
        """
        if self._raw_data is None:
            raise RuntimeError(
                "FileUploadConnector.extract_documents() called before connect()."
            )

        if self._file_type == "pdf":
            text = self._parse_pdf(self._raw_data)
        elif self._file_type == "docx":
            text = self._parse_docx(self._raw_data)
        elif self._file_type == "xlsx":
            text = self._parse_xlsx(self._raw_data)
        else:
            # csv / txt / md — plain UTF-8 text
            text = self._parse_text(self._raw_data)

        yield Document(
            source_id=uuid.UUID(self._source_id) if self._source_id else uuid.uuid4(),
            raw_text=text,
            raw_storage_path=self._object_key,
            metadata={
                "file_type": self._file_type,
                "bucket": self._bucket,
            },
        )

    # ------------------------------------------------------------------
    # Connection health check
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """Return *True* when the object exists in MinIO, *False* otherwise."""
        try:
            return await self._storage.object_exists(
                bucket=self._bucket,
                object_key=self._object_key,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "FileUploadConnector.test_connection() raised unexpectedly "
                "for %s/%s",
                self._bucket,
                self._object_key,
            )
            return False

    # ------------------------------------------------------------------
    # Private parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        """Extract text from PDF bytes using PyPDF2."""
        import io  # noqa: PLC0415

        import PyPDF2  # type: ignore[import-untyped]  # noqa: PLC0415

        reader = PyPDF2.PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            page_text: str = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text)
        return "\n".join(parts)

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        """Extract text from DOCX bytes using python-docx."""
        import io  # noqa: PLC0415

        import docx  # type: ignore[import-untyped]  # noqa: PLC0415

        document = docx.Document(io.BytesIO(data))
        paragraphs: list[str] = [p.text for p in document.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    @staticmethod
    def _parse_xlsx(data: bytes) -> str:
        """Extract text from XLSX bytes using openpyxl."""
        import io  # noqa: PLC0415

        import openpyxl  # type: ignore[import-untyped]  # noqa: PLC0415

        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows: list[str] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_text = ",".join("" if v is None else str(v) for v in row)
                if row_text.strip(","):
                    rows.append(row_text)
        return "\n".join(rows)

    @staticmethod
    def _parse_text(data: bytes) -> str:
        """Decode plain-text bytes (csv / txt / md) as UTF-8."""
        return data.decode("utf-8", errors="replace")
