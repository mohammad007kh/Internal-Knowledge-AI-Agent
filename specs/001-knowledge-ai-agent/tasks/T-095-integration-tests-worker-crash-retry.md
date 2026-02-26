# T-095 · Integration Tests — Worker Crash & Retry (FR-033)

**Phase:** 9 — Testing, Polish & SC Verification
**Depends on:** T-092
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
Fernet (connection configs at rest)
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

## Goal

Verify FR-033: when a Celery worker crashes the backend's supervisor detects the failure and
writes a `system_health_events` row for each restart attempt. After 3 failed restarts a final
`restart_failed` row is written and no further attempts are made.

---

## Files to Create / Edit

```
src/backend/
  app/
    services/
      worker_health_service.py          ← supervisor logic (crash detection + retry)
    models/
      system_health_event.py            ← (already exists from T-065; shown for reference)
    routers/
      health.py                         ← GET /api/v1/health/workers (admin-only)

tests/
  integration/
    test_worker_crash_retry.py          ← main test file (FR-033)
    conftest_celery.py                  ← Celery fixtures isolated from main conftest

pyproject.toml                          ← ensure celery[pytest] extra present
```

---

## Implementation

### `src/backend/app/services/worker_health_service.py`

```python
"""
Worker health supervisor — FR-033.
Detects Celery worker heartbeat loss and records restart events in
system_health_events.  Max 3 restart attempts per component per window.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_health_event import SystemHealthEvent

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

MAX_RESTART_ATTEMPTS: int = 3
_COMPONENT_ATTEMPT_CACHE: dict[str, int] = {}  # component_name → attempt count


async def record_crash(
    db: AsyncSession,
    component_name: str,
    error_detail: str,
) -> SystemHealthEvent:
    """Record a crash event and determine if a restart should be attempted."""
    event = SystemHealthEvent(
        component_name=component_name,
        event_type="crash",
        attempt_number=0,
        error_detail=error_detail,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()

    current_attempts = _COMPONENT_ATTEMPT_CACHE.get(component_name, 0)
    log.warning(
        "Worker crash detected",
        extra={"component": component_name, "attempt_count": current_attempts},
    )

    if current_attempts < MAX_RESTART_ATTEMPTS:
        await _attempt_restart(db, component_name, current_attempts + 1, error_detail)
    else:
        await _record_restart_failed(db, component_name, error_detail)

    await db.commit()
    return event


async def _attempt_restart(
    db: AsyncSession,
    component_name: str,
    attempt_number: int,
    error_detail: str,
) -> None:
    attempt_event = SystemHealthEvent(
        component_name=component_name,
        event_type="restart_attempt",
        attempt_number=attempt_number,
        error_detail=error_detail,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(attempt_event)
    _COMPONENT_ATTEMPT_CACHE[component_name] = attempt_number
    log.info(
        "Restart attempt scheduled",
        extra={"component": component_name, "attempt": attempt_number},
    )


async def _record_restart_failed(
    db: AsyncSession,
    component_name: str,
    error_detail: str,
) -> None:
    failed_event = SystemHealthEvent(
        component_name=component_name,
        event_type="restart_failed",
        attempt_number=MAX_RESTART_ATTEMPTS,
        error_detail=error_detail,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(failed_event)
    log.error(
        "Max restart attempts exhausted — no further retries",
        extra={"component": component_name},
    )


async def record_restart_ok(
    db: AsyncSession,
    component_name: str,
) -> SystemHealthEvent:
    """Call this when a restarted worker successfully reports healthy."""
    _COMPONENT_ATTEMPT_CACHE.pop(component_name, None)
    event = SystemHealthEvent(
        component_name=component_name,
        event_type="restart_ok",
        attempt_number=0,
        error_detail=None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.commit()
    return event


def reset_attempt_counter(component_name: str) -> None:
    """Test helper — reset in-memory attempt cache for a component."""
    _COMPONENT_ATTEMPT_CACHE.pop(component_name, None)
```

---

### `src/backend/app/models/system_health_event.py`

```python
"""SQLAlchemy model for system_health_events (reference — created in T-065)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemHealthEvent(Base):
    __tablename__ = "system_health_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    component_name: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # crash | restart_attempt | restart_ok | restart_failed
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
```

---

### `src/backend/app/routers/health.py` (addition)

```python
"""Health endpoints — add workers status to existing health router."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.auth import require_admin
from app.models.system_health_event import SystemHealthEvent
from app.schemas.health import WorkerHealthSummary

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/workers",
    response_model=WorkerHealthSummary,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def get_worker_health(db: AsyncSession = Depends(get_db)) -> WorkerHealthSummary:
    """Return count of recent worker health events grouped by event_type."""
    rows = await db.execute(
        select(
            SystemHealthEvent.component_name,
            SystemHealthEvent.event_type,
            func.count(SystemHealthEvent.id).label("count"),
        ).group_by(
            SystemHealthEvent.component_name,
            SystemHealthEvent.event_type,
        )
    )
    events = rows.all()
    return WorkerHealthSummary(
        events=[
            {"component": r.component_name, "event_type": r.event_type, "count": r.count}
            for r in events
        ]
    )
```

---

### `src/backend/app/schemas/health.py` (addition)

```python
from pydantic import BaseModel


class WorkerEventCount(BaseModel):
    component: str
    event_type: str
    count: int


class WorkerHealthSummary(BaseModel):
    events: list[WorkerEventCount]
```

---

### `tests/integration/conftest_celery.py`

```python
"""
Isolated Celery fixtures for integration tests.
Does NOT import from main conftest to avoid fixture collisions.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from celery import Celery
from celery.contrib.pytest import celery_app, celery_worker  # noqa: F401 – re-export

CELERY_TEST_CONFIG = {
    "broker_url": "memory://",
    "result_backend": "cache+memory://",
    "task_always_eager": False,
    "task_eager_propagates": True,
}


@pytest.fixture(scope="session")
def celery_config():
    return CELERY_TEST_CONFIG


@pytest.fixture(scope="session")
def celery_parameters():
    return {"strict_typing": False}
```

---

### `tests/integration/test_worker_crash_retry.py`

```python
"""
FR-033 — Worker crash detection and retry integration tests.

Scenarios
---------
1. Single crash  → one 'crash' row + one 'restart_attempt' row (attempt=1)
2. Three crashes → three 'crash' rows + three 'restart_attempt' rows
3. Fourth crash  → 'crash' row + 'restart_failed' row; NO new 'restart_attempt'
4. Successful restart after single crash → 'restart_ok' clears counter
5. GET /api/v1/health/workers (admin) returns event summary

All DB operations use the async test session; in-memory attempt cache
is reset between tests via worker_health_service.reset_attempt_counter.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_health_event import SystemHealthEvent
from app.services.worker_health_service import (
    MAX_RESTART_ATTEMPTS,
    record_crash,
    record_restart_ok,
    reset_attempt_counter,
)

COMPONENT = "celery-worker"
ERROR_MSG = "Simulated OOM crash"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_events(
    db: AsyncSession,
    component: str,
    event_type: str,
) -> list[SystemHealthEvent]:
    result = await db.execute(
        select(SystemHealthEvent)
        .where(SystemHealthEvent.component_name == component)
        .where(SystemHealthEvent.event_type == event_type)
        .order_by(SystemHealthEvent.timestamp)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def reset_counter():
    """Ensure in-memory counter is clean before and after each test."""
    reset_attempt_counter(COMPONENT)
    yield
    reset_attempt_counter(COMPONENT)


# ---------------------------------------------------------------------------
# Tests — crash event logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_crash_writes_crash_and_attempt_rows(
    db_session: AsyncSession,
) -> None:
    """First crash → 'crash' + 'restart_attempt(1)' rows written."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    crashes = await _get_events(db_session, COMPONENT, "crash")
    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")

    assert len(crashes) == 1
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1


@pytest.mark.asyncio
async def test_second_crash_increments_attempt_number(
    db_session: AsyncSession,
) -> None:
    """Second crash → attempt_number=2."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")
    assert len(attempts) == 2
    attempt_numbers = {a.attempt_number for a in attempts}
    assert attempt_numbers == {1, 2}


@pytest.mark.asyncio
async def test_third_crash_writes_third_attempt(
    db_session: AsyncSession,
) -> None:
    """Third crash (= MAX_RESTART_ATTEMPTS) → attempt_number=3; no restart_failed yet."""
    for _ in range(MAX_RESTART_ATTEMPTS):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")
    failed = await _get_events(db_session, COMPONENT, "restart_failed")

    assert len(attempts) == MAX_RESTART_ATTEMPTS
    assert len(failed) == 0


# ---------------------------------------------------------------------------
# Tests — max attempts exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fourth_crash_writes_restart_failed_not_attempt(
    db_session: AsyncSession,
) -> None:
    """
    Fourth crash exceeds MAX_RESTART_ATTEMPTS.
    Expect:
    - 4 'crash' rows
    - 3 'restart_attempt' rows  (not 4)
    - 1 'restart_failed' row
    """
    for _ in range(MAX_RESTART_ATTEMPTS + 1):  # 4 crashes
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    crashes = await _get_events(db_session, COMPONENT, "crash")
    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")
    failed = await _get_events(db_session, COMPONENT, "restart_failed")

    assert len(crashes) == MAX_RESTART_ATTEMPTS + 1
    assert len(attempts) == MAX_RESTART_ATTEMPTS
    assert len(failed) == 1
    assert failed[0].attempt_number == MAX_RESTART_ATTEMPTS


@pytest.mark.asyncio
async def test_fifth_crash_writes_no_new_attempt_or_failed(
    db_session: AsyncSession,
) -> None:
    """
    After max exhausted, a 5th crash adds a 'crash' row but no new
    'restart_attempt' or duplicate 'restart_failed'.
    """
    for _ in range(MAX_RESTART_ATTEMPTS + 1):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    # 5th crash
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")
    failed = await _get_events(db_session, COMPONENT, "restart_failed")

    assert len(attempts) == MAX_RESTART_ATTEMPTS  # still 3, not 4
    assert len(failed) == 1  # still 1, not 2


# ---------------------------------------------------------------------------
# Tests — successful restart resets counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_ok_resets_counter(
    db_session: AsyncSession,
) -> None:
    """
    After a crash + successful restart, next crash starts a fresh counter.
    """
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    await record_restart_ok(db_session, COMPONENT)

    # Subsequent crash should trigger attempt_number=1 again
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    attempts = await _get_events(db_session, COMPONENT, "restart_attempt")
    ok_events = await _get_events(db_session, COMPONENT, "restart_ok")

    assert len(ok_events) == 1
    # Two restart_attempt rows: one before ok, one after
    assert len(attempts) == 2
    assert attempts[-1].attempt_number == 1


# ---------------------------------------------------------------------------
# Tests — API endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_health_endpoint_returns_summary(
    async_client: AsyncClient,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/health/workers (admin) — returns event counts."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    response = await async_client.get(
        "/api/v1/health/workers",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    events = body["events"]
    event_types = {e["event_type"] for e in events}
    assert "crash" in event_types
    assert "restart_attempt" in event_types


@pytest.mark.asyncio
async def test_worker_health_endpoint_requires_admin(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """Regular user must receive 403 from /health/workers."""
    response = await async_client.get(
        "/api/v1/health/workers",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_worker_health_endpoint_401_unauthenticated(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get("/api/v1/health/workers")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests — event_type constraint enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_failed_row_contains_correct_attempt_number(
    db_session: AsyncSession,
) -> None:
    """restart_failed row must record attempt_number = MAX_RESTART_ATTEMPTS (3)."""
    for _ in range(MAX_RESTART_ATTEMPTS + 1):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    failed = await _get_events(db_session, COMPONENT, "restart_failed")
    assert failed[0].attempt_number == MAX_RESTART_ATTEMPTS


@pytest.mark.asyncio
async def test_events_have_timestamps(
    db_session: AsyncSession,
) -> None:
    """All written events must have non-null UTC timestamps."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    events = await db_session.execute(
        select(SystemHealthEvent).where(
            SystemHealthEvent.component_name == COMPONENT
        )
    )
    for evt in events.scalars().all():
        assert evt.timestamp is not None
        assert evt.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_multiple_components_tracked_independently(
    db_session: AsyncSession,
) -> None:
    """Two different component names maintain separate attempt counters."""
    comp_a = "celery-worker"
    comp_b = "celery-beat"
    reset_attempt_counter(comp_b)

    try:
        # Exhaust retries for comp_a
        for _ in range(MAX_RESTART_ATTEMPTS + 1):
            await record_crash(db_session, comp_a, ERROR_MSG)

        # comp_b still allows retries
        await record_crash(db_session, comp_b, ERROR_MSG)

        failed_a = await _get_events(db_session, comp_a, "restart_failed")
        failed_b = await _get_events(db_session, comp_b, "restart_failed")
        attempts_b = await _get_events(db_session, comp_b, "restart_attempt")

        assert len(failed_a) == 1
        assert len(failed_b) == 0
        assert len(attempts_b) == 1
    finally:
        reset_attempt_counter(comp_b)
```

---

## `pyproject.toml` — Ensure Celery pytest extra

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "pytest-cov>=5.0",
    "celery[pytest]>=5.3",     # ← required for celery.contrib.pytest
    "factory-boy>=3.3",
    "faker>=25.0",
]
```

---

## pytest.ini (confirm asyncio_mode)

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = --strict-markers -q
```

---

## Definition of Done

- [ ] `worker_health_service.py` created; `MAX_RESTART_ATTEMPTS = 3` constant enforced
- [ ] `system_health_events` rows written for every crash, attempt, ok, and failed event
- [ ] Fourth crash triggers `restart_failed` — not a fourth `restart_attempt`
- [ ] `record_restart_ok` clears in-memory counter; subsequent crash restarts count from 1
- [ ] Multiple components tracked independently via `_COMPONENT_ATTEMPT_CACHE`
- [ ] `GET /api/v1/health/workers` returns `WorkerHealthSummary`; 403 for non-admin; 401 unauthenticated
- [ ] All 11 integration tests pass with `pytest tests/integration/test_worker_crash_retry.py -v`
- [ ] No hanging DB transactions; each test rolls back via `db_session` fixture from conftest
