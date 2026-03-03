"""T-098: X-Request-ID correlation tests.

Covers:
* Client-supplied ``x-request-id`` is echoed back verbatim in the response.
* Server generates a valid UUID-4 when the header is absent.
* The ``request_id`` field appears in structured log lines for that request.
* Concurrent requests with different IDs are tracked independently (context
  isolation via ``structlog.contextvars``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

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

    @pytest.mark.asyncio
    async def test_client_request_id_echoed_in_response(client, log_capture):
        req_id = str(uuid.uuid4())
        r = await client.get("/api/v1/health", headers={"x-request-id": req_id})
        assert r.headers.get("x-request-id") == req_id

    @pytest.mark.asyncio
    async def test_server_generates_request_id_if_absent(client, log_capture):
        r = await client.get("/api/v1/health")
        header_val = r.headers.get("x-request-id")
        assert header_val is not None, "x-request-id header should always be set"
        uuid.UUID(header_val)  # must be a valid UUID

    @pytest.mark.asyncio
    async def test_request_id_present_in_log_lines(client, log_capture):
        req_id = str(uuid.uuid4())
        await client.get("/api/v1/health", headers={"x-request-id": req_id})
        found = any(
            json.loads(rec).get("request_id") == req_id
            for rec in log_capture.records
            if rec.strip()
        )
        assert found, f"request_id={req_id!r} not found in any log line"

    @pytest.mark.asyncio
    async def test_request_id_isolation_per_request(client, log_capture):
        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())
        await asyncio.gather(
            client.get("/api/v1/health", headers={"x-request-id": id1}),
            client.get("/api/v1/health", headers={"x-request-id": id2}),
        )
        ids_in_logs = {
            json.loads(rec).get("request_id")
            for rec in log_capture.records
            if rec.strip()
        }
        assert id1 in ids_in_logs, f"id1={id1!r} missing from logs"
        assert id2 in ids_in_logs, f"id2={id2!r} missing from logs"
        # No stray IDs (None is allowed for log lines outside a request context)
        assert ids_in_logs <= {id1, id2, None}
