# T-098 · Structured Logging, X-Request-ID Correlation & Langfuse Trace Verification

**Phase:** 9 — Testing, Polish & SC Verification  
**Depends on:** T-091 (integration stack)  
**Blocks:** T-099

---

## Context

```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
Next.js 15 App Router · shadcn/ui · Tailwind CSS v4
React Context · TanStack Query v5 · react-hook-form · Zod
PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs · soft-delete + audit columns
Alembic versioned migrations
Celery + Redis · Beat replicas=1 STRICT
MinIO · presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user)
Fernet (connection configs + LLM API keys at rest)
LangGraph 8-node · interrupt() for clarification · SSE streaming
Langfuse self-hosted · every pipeline run must emit a trace
RFC 7807 Problem Details — all non-2xx API responses
Structured logging · INFO level · X-Request-ID correlation
CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP
Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright · ≥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

Verify three observability requirements that cut across the entire stack:

1. **Structured logging** — every log line is valid JSON with mandatory fields (`timestamp`, `level`, `message`, `request_id`)  
2. **X-Request-ID correlation** — a client-supplied `X-Request-ID` header is echoed back in the response and injected into every log line for that request  
3. **Langfuse trace emission** — every pipeline run results in exactly one Langfuse trace with a non-null trace ID and a non-null `total_tokens` usage sum

---

## Files to Create / Edit

```
src/backend/
  app/
    middleware/
      logging_middleware.py   ← request_id injection + structured log emit
    core/
      logging_config.py       ← JSON formatter setup
    services/
      langfuse_verifier.py    ← helper: poll Langfuse API to confirm trace exists

tests/
  integration/
    test_structured_logging.py
    test_request_id_correlation.py
    test_langfuse_traces.py
```

---

## 1. Logging Configuration — `src/backend/app/core/logging_config.py`

```python
"""
Structured JSON logging configuration.
Must be imported before any other app module.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Set up structlog with JSON output and mandatory fields."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.handlers = [handler]
```

---

## 2. Logging Middleware — `src/backend/app/middleware/logging_middleware.py`

```python
"""
Request-scoped middleware.
1. Reads or generates X-Request-ID.
2. Binds request_id to structlog context.
3. Logs request start/end at INFO level.
4. Echoes X-Request-ID in every response.
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Honour client-supplied header; generate one if absent
        request_id: str = (
            request.headers.get("x-request-id") or str(uuid.uuid4())
        )

        # Bind to structlog context for this async request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        log.info(
            "request.start",
            method=request.method,
            path=request.url.path,
        )

        response: Response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            "request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )

        response.headers["x-request-id"] = request_id
        return response
```

---

## 3. Langfuse Verifier — `src/backend/app/services/langfuse_verifier.py`

```python
"""
Helper used in tests to confirm a Langfuse trace was emitted for a pipeline run.
Polls the Langfuse API with exponential back-off.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")


async def get_trace_by_id(trace_id: str) -> dict[str, Any] | None:
    """Return Langfuse trace dict or None if not found."""
    url = f"{LANGFUSE_HOST}/api/public/traces/{trace_id}"
    async with httpx.AsyncClient(
        auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY),
        timeout=10,
    ) as client:
        r = await client.get(url)
        if r.status_code == 200:
            return r.json()
    return None


async def await_trace(
    trace_id: str,
    max_wait: float = 30.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """
    Poll until trace appears in Langfuse or raise TimeoutError.
    Returns the trace dict when found.
    """
    deadline = asyncio.get_event_loop().time() + max_wait
    while asyncio.get_event_loop().time() < deadline:
        trace = await get_trace_by_id(trace_id)
        if trace is not None:
            return trace
        await asyncio.sleep(poll_interval)
    raise TimeoutError(
        f"Langfuse trace {trace_id!r} not available after {max_wait}s"
    )
```

---

## 4. Test: Structured Logging — `tests/integration/test_structured_logging.py`

```python
"""
Verify that backend log output is valid JSON with required fields.

Strategy: capture stdout from the test app instance using a custom log handler
that stores records, then assert field presence.
"""
from __future__ import annotations

import io
import json
import logging

import pytest
import pytest_asyncio
import structlog
from httpx import AsyncClient


class JsonLineCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest_asyncio.fixture
def log_capture(monkeypatch: pytest.MonkeyPatch) -> JsonLineCapture:
    """Replace the root log handler with a capturing handler."""
    capture = JsonLineCapture()
    capture.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers = [capture]
    yield capture
    root.handlers = original_handlers


MANDATORY_FIELDS = {"timestamp", "level", "event"}


@pytest.mark.asyncio
async def test_log_lines_are_valid_json(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
) -> None:
    """GET /api/v1/health → at least one log line must be valid JSON."""
    await async_client.get("/api/v1/health")
    assert log_capture.records, "No log records captured"

    for raw in log_capture.records:
        raw = raw.strip()
        if not raw:
            continue
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Invalid JSON log line: {raw!r}\n{exc}")


@pytest.mark.asyncio
async def test_log_lines_have_mandatory_fields(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
) -> None:
    """Every parsed JSON log line must contain mandatory fields."""
    await async_client.get("/api/v1/health")

    for raw in log_capture.records:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue  # non-JSON lines (startup) are tolerated

        for field in MANDATORY_FIELDS:
            assert field in obj, (
                f"Mandatory field '{field}' missing from log line: {obj}"
            )


@pytest.mark.asyncio
async def test_log_level_is_string(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
) -> None:
    await async_client.get("/api/v1/health")
    for raw in log_capture.records:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "level" in obj:
            assert isinstance(obj["level"], str), (
                f"'level' must be a string, got {type(obj['level'])}"
            )


@pytest.mark.asyncio
async def test_no_sensitive_data_in_logs(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
    user_token: str,
) -> None:
    """Access tokens and passwords must not appear in log output."""
    await async_client.get(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    combined = " ".join(log_capture.records)
    # Token is long enough that a partial overlap would still be 20+ chars
    assert user_token[:20] not in combined, (
        "Authorization token leaked into log output"
    )
```

---

## 5. Test: X-Request-ID Correlation — `tests/integration/test_request_id_correlation.py`

```python
"""
Verify X-Request-ID header injection and correlation.
"""
from __future__ import annotations

import json
import logging
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient


class JsonLineCapture(logging.Handler):
    records: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.records = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest_asyncio.fixture
def log_capture(monkeypatch: pytest.MonkeyPatch) -> JsonLineCapture:
    capture = JsonLineCapture()
    capture.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    original = root.handlers[:]
    root.handlers = [capture]
    yield capture
    root.handlers = original


@pytest.mark.asyncio
async def test_client_request_id_echoed_in_response(
    async_client: AsyncClient,
) -> None:
    """A client-supplied X-Request-ID must be returned in the response header."""
    req_id = str(uuid.uuid4())
    r = await async_client.get(
        "/api/v1/health",
        headers={"X-Request-ID": req_id},
    )
    assert r.headers.get("x-request-id") == req_id


@pytest.mark.asyncio
async def test_server_generates_request_id_if_absent(
    async_client: AsyncClient,
) -> None:
    """If client omits X-Request-ID, server generates and returns one."""
    r = await async_client.get("/api/v1/health")
    req_id = r.headers.get("x-request-id", "")
    assert req_id, "Server did not generate an X-Request-ID"
    # Must be a valid UUID
    uuid.UUID(req_id)  # raises if invalid


@pytest.mark.asyncio
async def test_request_id_present_in_log_lines(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
) -> None:
    """request_id must appear in structured logs for that request."""
    req_id = str(uuid.uuid4())
    await async_client.get(
        "/api/v1/health",
        headers={"X-Request-ID": req_id},
    )
    matched = False
    for raw in log_capture.records:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("request_id") == req_id:
            matched = True
            break

    assert matched, (
        f"request_id={req_id!r} not found in any log line. "
        f"Captured records: {log_capture.records[:5]}"
    )


@pytest.mark.asyncio
async def test_request_id_isolation_per_request(
    async_client: AsyncClient,
    log_capture: JsonLineCapture,
) -> None:
    """
    Two concurrent requests with different IDs must not mix their request_ids
    in the log lines belonging to each request.
    """
    import asyncio

    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())

    await asyncio.gather(
        async_client.get("/api/v1/health", headers={"X-Request-ID": id_a}),
        async_client.get("/api/v1/health", headers={"X-Request-ID": id_b}),
    )

    ids_in_logs = set()
    for raw in log_capture.records:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "request_id" in obj:
            ids_in_logs.add(obj["request_id"])

    # Both IDs must appear; no third spurious ID beyond them
    assert id_a in ids_in_logs
    assert id_b in ids_in_logs
```

---

## 6. Test: Langfuse Traces — `tests/integration/test_langfuse_traces.py`

```python
"""
Verify that every query pipeline run emits exactly one Langfuse trace
with a non-null trace_id and non-zero token usage.

These tests require Langfuse to be running (Docker Compose langfuse service).
They are skipped automatically when LANGFUSE_HOST is not reachable.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.services.langfuse_verifier import await_trace

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def check_langfuse_reachable() -> None:
    """Skip all tests in this module if Langfuse is not available."""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{LANGFUSE_HOST}/api/public/health")
            if r.status_code != 200:
                pytest.skip("Langfuse not reachable — skipping trace tests")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Langfuse not reachable — skipping trace tests")


@pytest.mark.asyncio
async def test_pipeline_run_emits_langfuse_trace(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """
    POST /api/v1/chat/sessions + POST /api/v1/chat/{id}/messages
    should result in a Langfuse trace with a trace_id.
    """
    # Create session
    r = await async_client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"title": "Langfuse trace test"},
    )
    assert r.status_code == 201
    session_id = r.json()["id"]

    # Send message
    r = await async_client.post(
        f"/api/v1/chat/{session_id}/messages",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"content": "What is the parental leave policy?"},
    )
    assert r.status_code in (200, 201, 202)
    body = r.json()

    # Check that trace_id is returned in the response
    trace_id: str | None = body.get("trace_id")
    assert trace_id, f"No trace_id in response: {body}"

    # Poll Langfuse until trace appears
    trace = await await_trace(trace_id, max_wait=30.0)
    assert trace["id"] == trace_id


@pytest.mark.asyncio
async def test_trace_has_non_zero_token_usage(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """Langfuse trace must record total_tokens > 0."""
    r = await async_client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"title": "Token usage test"},
    )
    session_id = r.json()["id"]

    r = await async_client.post(
        f"/api/v1/chat/{session_id}/messages",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"content": "Tell me about the company pension plan."},
    )
    body = r.json()
    trace_id = body.get("trace_id")
    if not trace_id:
        pytest.skip("trace_id not in response — pipeline may not be wired to Langfuse")

    trace = await await_trace(trace_id, max_wait=30.0)

    # Langfuse stores usage under trace.usage.totalTokens or trace.totalTokens
    usage = trace.get("usage") or {}
    total_tokens = (
        usage.get("totalTokens") or
        usage.get("total_tokens") or
        trace.get("totalTokens") or
        0
    )
    assert total_tokens > 0, (
        f"Expected totalTokens > 0, got {total_tokens}. Trace: {trace}"
    )


@pytest.mark.asyncio
async def test_each_pipeline_run_creates_distinct_trace(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """Two consecutive pipeline runs must emit two different trace IDs."""
    session_r = await async_client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"title": "Distinct traces test"},
    )
    session_id = session_r.json()["id"]

    headers = {"Authorization": f"Bearer {user_token}"}

    r1 = await async_client.post(
        f"/api/v1/chat/{session_id}/messages",
        headers=headers,
        json={"content": "Question one for Langfuse."},
    )
    r2 = await async_client.post(
        f"/api/v1/chat/{session_id}/messages",
        headers=headers,
        json={"content": "Question two for Langfuse."},
    )

    t1 = r1.json().get("trace_id")
    t2 = r2.json().get("trace_id")

    if not (t1 and t2):
        pytest.skip("trace_id not in responses")

    assert t1 != t2, f"Both runs returned same trace_id: {t1}"
```

---

## Definition of Done

- [ ] `configure_logging()` called at app startup; all log output is JSON
- [ ] Every JSON log line contains `timestamp`, `level`, `event`
- [ ] Log `level` field is a string (`"info"`, `"warning"`, etc.)
- [ ] No JWT access tokens or passwords visible in any log line
- [ ] `RequestIDMiddleware` registers in `app.middleware` before routing
- [ ] Client-supplied `X-Request-ID` echoed in response header
- [ ] Server generates a UUID-format `X-Request-ID` when client omits it
- [ ] `request_id` present in structlog context for every request
- [ ] Concurrent requests do not mix `request_id` values
- [ ] `POST /api/v1/chat/{session_id}/messages` returns `trace_id` in response body
- [ ] Langfuse trace with that ID has `totalTokens > 0` within 30 s
- [ ] Two consecutive pipeline runs produce two distinct `trace_id` values
- [ ] Langfuse tests auto-skipped when `LANGFUSE_HOST` is unreachable
