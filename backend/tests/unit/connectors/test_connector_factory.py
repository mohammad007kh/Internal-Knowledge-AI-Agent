"""Unit tests for ConnectorFactory (T-057).

FR-020 compliance:
  - decrypted_config must NEVER appear in log output.
  - source_id and source_type.value ARE logged (positive assertion).
"""
from __future__ import annotations

import logging
import uuid
from unittest.mock import patch

import pytest

# Import connector modules to trigger @register side-effects
import src.connectors.database_connector  # noqa: F401
import src.connectors.file_upload_connector  # noqa: F401
import src.connectors.web_url_connector  # noqa: F401
from src.connectors.base import BaseConnector
from src.connectors.database_connector import DatabaseConnector
from src.connectors.factory import ConnectorFactory
from src.connectors.file_upload_connector import FileUploadConnector
from src.connectors.web_url_connector import WebUrlConnector
from src.models.enums import SourceType

_SOURCE_ID = str(uuid.uuid4())
_SENSITIVE_VALUE = "super_secret_password_xyz"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_factory() -> ConnectorFactory:
    return ConnectorFactory()


def _web_config() -> dict:
    return {"url": "https://example.com", "source_id": _SOURCE_ID}


def _file_config() -> dict:
    return {
        "minio_bucket": "uploads",
        "object_key": "docs/test.txt",
        "file_type": "txt",
        "source_id": _SOURCE_ID,
    }


def _db_config() -> dict:
    return {
        "connection_string": f"postgresql+asyncpg://user:{_SENSITIVE_VALUE}@localhost/db",
        "query": "SELECT id FROM tbl",
        "source_id": _SOURCE_ID,
    }


# ---------------------------------------------------------------------------
# build() — returns correct connector type
# ---------------------------------------------------------------------------


def test_build_web_url_returns_web_url_connector() -> None:
    factory = _make_factory()
    with patch("src.connectors.web_url_connector.StorageService"):
        connector = factory.build(
            source_type=SourceType.WEB_URL,
            source_id=_SOURCE_ID,
            decrypted_config=_web_config(),
        )
    assert isinstance(connector, WebUrlConnector)


def test_build_file_upload_returns_file_upload_connector() -> None:
    factory = _make_factory()
    with patch("src.connectors.file_upload_connector.StorageService"):
        connector = factory.build(
            source_type=SourceType.FILE_UPLOAD,
            source_id=_SOURCE_ID,
            decrypted_config=_file_config(),
        )
    assert isinstance(connector, FileUploadConnector)


def test_build_database_returns_database_connector() -> None:
    factory = _make_factory()
    connector = factory.build(
        source_type=SourceType.DATABASE,
        source_id=_SOURCE_ID,
        decrypted_config=_db_config(),
    )
    assert isinstance(connector, DatabaseConnector)


def test_build_returns_base_connector_subclass() -> None:
    factory = _make_factory()
    connector = factory.build(
        source_type=SourceType.DATABASE,
        source_id=_SOURCE_ID,
        decrypted_config=_db_config(),
    )
    assert isinstance(connector, BaseConnector)


# ---------------------------------------------------------------------------
# build() — unregistered type raises ValueError
# ---------------------------------------------------------------------------


def test_build_raises_value_error_for_unregistered_type() -> None:
    factory = _make_factory()
    with patch("src.connectors.factory.get_connector", side_effect=ValueError("not registered")):
        with pytest.raises(ValueError):
            factory.build(
                source_type=SourceType.CONFLUENCE,
                source_id=_SOURCE_ID,
                decrypted_config={"url": "https://confluence.example.com"},
            )


# ---------------------------------------------------------------------------
# FR-020: decrypted_config must NOT appear in logs
# ---------------------------------------------------------------------------


def test_build_does_not_log_decrypted_config() -> None:
    factory = _make_factory()
    db_cfg = _db_config()

    log_stream: list[str] = []
    handler = LogCapture(log_stream)

    factory_logger = logging.getLogger("src.connectors.factory")
    factory_logger.addHandler(handler)
    original_level = factory_logger.level
    factory_logger.setLevel(logging.DEBUG)

    try:
        factory.build(
            source_type=SourceType.DATABASE,
            source_id=_SOURCE_ID,
            decrypted_config=db_cfg,
        )
    finally:
        factory_logger.removeHandler(handler)
        factory_logger.setLevel(original_level)

    all_log = " ".join(log_stream)
    # Sensitive values must NOT appear in any log line
    assert _SENSITIVE_VALUE not in all_log, (
        "decrypted_config value leaked to logs — violates FR-020"
    )
    assert "super_secret" not in all_log, (
        "decrypted_config value leaked to logs — violates FR-020"
    )


def test_build_does_not_log_decrypted_config_dict_repr() -> None:
    """Even if config is repr'd as a dict string it must not appear in logs."""
    factory = _make_factory()
    db_cfg = _db_config()

    log_stream: list[str] = []
    handler = LogCapture(log_stream)

    factory_logger = logging.getLogger("src.connectors.factory")
    factory_logger.addHandler(handler)
    original_level = factory_logger.level
    factory_logger.setLevel(logging.DEBUG)

    try:
        factory.build(
            source_type=SourceType.DATABASE,
            source_id=_SOURCE_ID,
            decrypted_config=db_cfg,
        )
    finally:
        factory_logger.removeHandler(handler)
        factory_logger.setLevel(original_level)

    all_log = " ".join(log_stream)
    # The connection string contains a password; must not appear
    assert db_cfg["connection_string"] not in all_log, (
        "Connection string leaked to logs — violates FR-020"
    )


# ---------------------------------------------------------------------------
# FR-020 positive: source_id and source_type DO appear in logs
# ---------------------------------------------------------------------------


def test_build_logs_source_id() -> None:
    factory = _make_factory()

    log_stream: list[str] = []
    handler = LogCapture(log_stream)

    factory_logger = logging.getLogger("src.connectors.factory")
    factory_logger.addHandler(handler)
    original_level = factory_logger.level
    factory_logger.setLevel(logging.DEBUG)

    try:
        factory.build(
            source_type=SourceType.DATABASE,
            source_id=_SOURCE_ID,
            decrypted_config=_db_config(),
        )
    finally:
        factory_logger.removeHandler(handler)
        factory_logger.setLevel(original_level)

    all_log = " ".join(log_stream)
    assert _SOURCE_ID in all_log, "source_id should appear in factory log"


def test_build_logs_source_type() -> None:
    factory = _make_factory()

    log_stream: list[str] = []
    handler = LogCapture(log_stream)

    factory_logger = logging.getLogger("src.connectors.factory")
    factory_logger.addHandler(handler)
    original_level = factory_logger.level
    factory_logger.setLevel(logging.DEBUG)

    try:
        factory.build(
            source_type=SourceType.DATABASE,
            source_id=_SOURCE_ID,
            decrypted_config=_db_config(),
        )
    finally:
        factory_logger.removeHandler(handler)
        factory_logger.setLevel(original_level)

    all_log = " ".join(log_stream)
    assert SourceType.DATABASE.value in all_log, (
        "source_type.value should appear in factory log"
    )


# ---------------------------------------------------------------------------
# Log capture helper
# ---------------------------------------------------------------------------


class LogCapture(logging.Handler):
    """Captures formatted log messages into a list."""

    def __init__(self, target: list[str]) -> None:
        super().__init__()
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        self._target.append(self.format(record))
