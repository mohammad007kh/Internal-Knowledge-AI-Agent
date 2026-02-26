# T-019 — Celery App Factory + Worker + Beat Configuration

---
id: T-019
title: Celery Application Factory, Worker Dockerfile CMD, and Beat Scheduler
status: Not Started
created: 2026-02-26
phase: Phase 0 — Foundation
user_story: cross
requirements: [FR-016, FR-033]
priority: P1
depends_on: [T-004, T-018]
blocks: [T-061, T-062]
estimated_effort: 2h
---

## Goal

Set up the Celery application factory so that background tasks (file ingestion, sync, embedding refreshes) can be registered in later tasks. The beat scheduler is configured here but the actual schedule dictionary is populated in T-061. The worker and beat Dockerfile `CMD` instructions must be documented to keep the Docker Compose services correct.

---

## Acceptance Criteria

- [ ] `celery_app` is importable from `src.core.celery` with broker and backend pointing to `settings.REDIS_URL`
- [ ] `@shared_task` imports from `celery` (standard pattern — no direct `celery_app` reference in task files)
- [ ] Beat scheduler uses `celery_app.conf.beat_schedule` dict (not `django-celery-beat` database scheduler)
- [ ] Beat schedule is initially empty — populated in T-061
- [ ] Worker `CMD` in Dockerfile: `celery -A src.core.celery:celery_app worker --loglevel=info --concurrency=4`
- [ ] Beat `CMD` in Dockerfile: `celery -A src.core.celery:celery_app beat --loglevel=info --scheduler celery.beat:PersistentScheduler`
- [ ] Beat `replicas: 1` is enforced in `docker-compose.yml` — task documents the constraint (already in T-002, confirmed here)
- [ ] Task serializer: `json`; result serializer: `json`; accept content: `json` — no `pickle`
- [ ] Task auto-discovery scans `src.tasks.*` package
- [ ] `celery_app.conf.task_soft_time_limit = 300` and `task_time_limit = 360` (FR-033: auto-restart capped)
- [ ] Unit test: `celery_app` imports successfully; `celery_app.tasks` list does not raise
- [ ] Integration: `make celery-status` target (from T-006) connects to broker and returns worker list

---

## Files to Create / Update

| Path | Action |
|------|---------|
| `backend/src/core/celery.py` | Create — Celery app factory |
| `backend/src/tasks/__init__.py` | Create — empty package |
| `backend/src/tasks/base.py` | Create — `BaseTask` with retry + Sentry logging |
| `backend/Dockerfile.worker` | Create — worker + beat image (or document CMD override in docker-compose) |
| `backend/tests/unit/test_celery_app.py` | Create |

---

## Implementation

### `backend/src/core/celery.py`

```python
from celery import Celery
from src.core.config import settings

celery_app = Celery(
    "knowledge_agent",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.tasks"],  # auto-discovers src/tasks/*.py
)

celery_app.conf.update(
    # Serialization — never use pickle (security)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Timeouts (FR-033: cap retries)
    task_soft_time_limit=300,    # sends SoftTimeLimitExceeded at 5 min
    task_time_limit=360,         # hard kill at 6 min
    # Results
    result_expires=3600,         # keep results for 1 hour
    # Worker
    worker_prefetch_multiplier=1,
    task_acks_late=True,         # ack after completion, not on receive
    # Beat — schedule populated in T-061
    beat_schedule={},
    beat_max_loop_interval=5,
)
```

### `backend/src/tasks/base.py`

```python
import logging
import structlog
from celery import Task

logger = structlog.get_logger(__name__)


class BaseTask(Task):
    """
    All application tasks should inherit from this base.
    Provides:
    - Structured logging on start / success / failure
    - Automatic retry on temporary failures (3 attempts, exponential backoff)
    - Sentry error capture on final failure
    """
    abstract = True
    max_retries = 3
    default_retry_delay = 60  # seconds

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "celery_task_failed",
            task_id=task_id,
            task_name=self.name,
            exc=str(exc),
        )
        # Sentry capture (only if SDK is initialised — safe to call always)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(
            "celery_task_retry",
            task_id=task_id,
            task_name=self.name,
            exc=str(exc),
            retries=self.request.retries,
            max_retries=self.max_retries,
        )

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(
            "celery_task_success",
            task_id=task_id,
            task_name=self.name,
        )
```

### `backend/src/tasks/__init__.py`

```python
# Tasks are imported here so Celery auto-discovery finds them.
# Add imports as tasks are created in T-061, T-062, etc.
# Example (uncomment when task file exists):
# from src.tasks.sync import run_source_sync  # noqa: F401
```

### Task authoring pattern (for all future tasks in T-061+)

```python
# backend/src/tasks/sync.py
from celery import shared_task
from src.tasks.base import BaseTask

@shared_task(bind=True, base=BaseTask, name="tasks.run_source_sync")
def run_source_sync(self, source_id: str) -> dict:
    """
    Sync a single source. Called by Beat and manual triggers.
    """
    # implementation in T-061
    ...
```

### Docker Compose CMD overrides (already in T-002, confirmed here)

```yaml
# docker-compose.yml — worker service
worker:
  build:
    context: ./backend
  command: celery -A src.core.celery:celery_app worker --loglevel=info --concurrency=4
  depends_on:
    redis:
      condition: service_healthy
    db:
      condition: service_healthy

# docker-compose.yml — beat service
beat:
  build:
    context: ./backend
  command: celery -A src.core.celery:celery_app beat --loglevel=info
  deploy:
    replicas: 1  # CRITICAL — duplicate beat schedules cause duplicate task execution
  depends_on:
    redis:
      condition: service_healthy
```

---

## Tests

### `backend/tests/unit/test_celery_app.py`

```python
import pytest
from unittest.mock import patch


def test_celery_app_imports():
    """Celery app module imports without error."""
    from src.core.celery import celery_app
    assert celery_app is not None
    assert celery_app.main == "knowledge_agent"


def test_celery_serialization_config():
    """Verify no pickle serialization."""
    from src.core.celery import celery_app
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert "json" in celery_app.conf.accept_content


def test_celery_timeouts_configured():
    """Timeout limits present (FR-033)."""
    from src.core.celery import celery_app
    assert celery_app.conf.task_soft_time_limit == 300
    assert celery_app.conf.task_time_limit == 360


def test_base_task_on_failure_calls_sentry(caplog):
    """on_failure logs an error message."""
    from src.tasks.base import BaseTask
    task = BaseTask()
    task.name = "test.dummy"
    with patch("sentry_sdk.capture_exception") as mock_capture:
        task.on_failure(Exception("boom"), "task-id-1", [], {}, None)
        mock_capture.assert_called_once()
```

---

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- **Beat MUST run with `replicas: 1`** — this is a hard rule; duplicate beat instances cause tasks to fire multiple times
- Never use `pickle` serialization — json only
- `task_acks_late=True` + `worker_prefetch_multiplier=1` ensures tasks are not lost on worker crash
- `FR-033`: Auto-restart is capped at 3 attempts (`max_retries=3` in `BaseTask`); on final failure alert via Sentry
- The beat schedule dict lives in `celery_app.conf.beat_schedule` — not in a database scheduler
