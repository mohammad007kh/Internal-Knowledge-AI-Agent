"""T-098: structured JSON logging tests.

Verifies that every log line emitted during a request is valid JSON and
contains the mandatory structlog fields: ``timestamp``, ``level``, and
``event``.  Also checks that bearer tokens never appear in log output.

All tests are guarded by ``RUN_INTEGRATION_TESTS=1`` so the suite is safe
to collect in any environment.
"""
from __future__ import annotations

import json
import logging
import os

import pytest

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

if _INTEGRATION:

    class JsonLineCapture(logging.Handler):
        """Collects formatted log lines for inspection."""

        def __init__(self) -> None:
            super().__init__()
            self.records: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(self.format(record))

    @pytest.fixture
    def log_capture():
        """Temporarily replaces the root logger handler with a capturing one."""
        handler = JsonLineCapture()
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        root.handlers = [handler]
        yield handler
        root.handlers = old_handlers

    # structlog TimeStamper → "timestamp"; add_log_level → "level"; message key → "event"
    MANDATORY_FIELDS = {"timestamp", "level", "event"}

    @pytest.mark.asyncio
    async def test_log_lines_are_valid_json(client, log_capture):
        await client.get("/api/v1/health")
        assert log_capture.records, "expected at least one log line"
        for rec in log_capture.records:
            json.loads(rec)  # must not raise

    @pytest.mark.asyncio
    async def test_log_lines_have_mandatory_fields(client, log_capture):
        await client.get("/api/v1/health")
        for rec in log_capture.records:
            if not rec.strip():
                continue
            data = json.loads(rec)
            missing = MANDATORY_FIELDS - data.keys()
            assert not missing, f"Log line missing fields {missing}: {rec}"

    @pytest.mark.asyncio
    async def test_log_level_is_string(client, log_capture):
        await client.get("/api/v1/health")
        for rec in log_capture.records:
            if not rec.strip():
                continue
            data = json.loads(rec)
            if "level" in data:
                assert isinstance(data["level"], str)

    @pytest.mark.asyncio
    async def test_no_sensitive_data_in_logs(client, log_capture, user_token):
        await client.get(
            "/api/v1/health",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        all_output = "\n".join(log_capture.records)
        assert user_token not in all_output
