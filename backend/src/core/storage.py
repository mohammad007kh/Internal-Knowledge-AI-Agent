"""Object-storage (MinIO) client — stub for T-035 tests.

Full implementation in T-030 (document upload endpoints).
``minio_client`` is a module-level singleton so integration tests can
patch it at ``src.core.storage.minio_client``.
"""
from typing import Any
from unittest.mock import MagicMock

# Stub client — replaced by real MinioClient in T-030
minio_client: Any = MagicMock()

__all__ = ["minio_client"]
