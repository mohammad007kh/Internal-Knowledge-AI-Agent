# T-022: Backend — check_scheduled_syncs Celery Task + next_sync_due_at Logic

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want sources configured with a cron schedule to automatically re-sync at the right time without manual intervention.
- **Requirement**: FR-038 (scheduled sync task runs every 60s), FR-039 (next_sync_due_at computed from cron), FR-040 (sync dispatched for due sources)
- **Priority**: P2

---

## 📋 Embedded Context

### Registry Standards (locked for this project)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `backend.job_queue` | celery + Redis |
| `backend.beat_pattern` | polling_task_60s |
| `conventions.files` | snake_case (Python) |
| `conventions.variables` | snake_case |
| `database.tenancy_model` | single_tenant |
| `backend.language` | python |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |

### Hard Constraints (Constitution §V)
- Celery Beat runs as a SINGLE REPLICA — `replicas: 1` in docker-compose. Never increase.
- The `check_scheduled_syncs` task is a lightweight dispatcher only — it reads DB, fires `sync_source.delay(id)`, updates `next_sync_due_at`. It does NOT do the actual ingestion.
- `next_sync_due_at` is the only polling column — no additional cron scheduler packages.
- All Celery tasks are idempotent: if a source is already `ingesting`, skip it (filtered in the query).

### Domain Rules
- `sync_schedule` is a standard cron expression (5 parts: min hour day month weekday).
- Use `croniter` library (already available or add to pyproject.toml if missing) to compute next fire time.
- `next_sync_due_at` must be updated in three places:
  1. When a source is first saved with `sync_mode = 'scheduled'`.
  2. When a sync job completes (in `sync_source` task's success handler).
  3. When admin updates the `sync_schedule` on a source.
- Query must be efficient: use `ix_sources_sync_poll` index created in T-001 migration.

### Gate Criteria
- Task fires every 60 seconds via `beat_schedule`.
- Query filters: `sync_mode='scheduled'`, `next_sync_due_at <= NOW()`, `status NOT IN ('ingesting','paused')`.
- For each matching source: `sync_source.delay(source_id)` is called, `next_sync_due_at` updated.
- `next_sync_due_at` computed correctly from cron expression using `croniter`.
- No duplicate dispatches for the same source in the same minute.

---

## 🎯 Objective

Implement the `check_scheduled_syncs` Celery periodic task that polls the DB every 60 seconds and dispatches ingestion for any sources whose `next_sync_due_at` has passed. Also implement the `next_sync_due_at` computation helper used in source create/update flows.

---

## 🛠️ Implementation Details

### Files to Update/Create

1. **`backend/src/tasks/scheduled_sync.py`** (new file):

```python
from celery import shared_task
from datetime import datetime, timezone
from croniter import croniter
from sqlalchemy import select, update
from src.db.session import async_session_factory
from src.models.source import Source
from src.tasks.ingestion import sync_source  # existing task


@shared_task(name='tasks.check_scheduled_syncs', max_retries=0, ignore_result=True)
def check_scheduled_syncs() -> None:
    """Dispatcher: find due scheduled sources and fire sync_source for each."""
    import asyncio
    asyncio.run(_check_scheduled_syncs_async())


async def _check_scheduled_syncs_async() -> None:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        result = await session.execute(
            select(Source)
            .where(
                Source.sync_mode == 'scheduled',
                Source.next_sync_due_at <= now,
                Source.status.notin_(['ingesting', 'paused']),
            )
        )
        sources = result.scalars().all()
        for source in sources:
            sync_source.delay(str(source.id))
            next_due = compute_next_sync_due(source.sync_schedule)
            await session.execute(
                update(Source)
                .where(Source.id == source.id)
                .values(next_sync_due_at=next_due)
            )
        await session.commit()


def compute_next_sync_due(cron_expression: str) -> datetime:
    """Return the next fire time for a cron expression (UTC)."""
    now = datetime.now(timezone.utc)
    return croniter(cron_expression, now).get_next(datetime)
```

2. **`backend/src/celery_app.py`** (or wherever `beat_schedule` is defined) — Register the task:

```python
beat_schedule = {
    'check-scheduled-syncs': {
        'task': 'tasks.check_scheduled_syncs',
        'schedule': 60.0,  # every 60 seconds
    },
    # ... existing tasks
}
```

3. **`backend/src/services/source_service.py`** (update) — Call `compute_next_sync_due` when:
   - Creating a source with `sync_mode='scheduled'`: set `next_sync_due_at = compute_next_sync_due(sync_schedule)`.
   - Updating `sync_schedule` on an existing source: recompute and save.
   - After sync completes (in `sync_source` task success handler): recompute from source's current schedule.

4. **`backend/pyproject.toml`** — Verify or add `croniter`:
   ```toml
   croniter = "^2.0"
   ```

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `check_scheduled_syncs` registered in `beat_schedule` with `schedule=60.0`.
- [ ] Task imported in Celery app so it is auto-discovered.
- [ ] `compute_next_sync_due` called on source create/update when `sync_mode='scheduled'`.
- [ ] `compute_next_sync_due` called in `sync_source` success handler to schedule next run.
- [ ] Query filters out `ingesting` and `paused` sources.
- [ ] `croniter` in `pyproject.toml` (or equivalent).

---

## ✅ Verification

```bash
cd backend && python -c "
from src.tasks.scheduled_sync import compute_next_sync_due
from datetime import datetime, timezone
result = compute_next_sync_due('0 2 * * *')
assert isinstance(result, datetime), 'must return datetime'
assert result.tzinfo is not None, 'must be timezone-aware'
print('OK: next due =', result)
"
```
Expected: prints `OK: next due = <future UTC datetime>`.

Also verify beat registration:
```bash
cd backend && python -c "
from src.celery_app import app
assert 'check-scheduled-syncs' in app.conf.beat_schedule, 'missing beat entry'
print('OK: beat schedule registered')
"
```

---

## 📝 Completion Log

- [ ] `check_scheduled_syncs` task implemented.
- [ ] `compute_next_sync_due` helper implemented and tested.
- [ ] Beat schedule registered at 60s interval.
- [ ] Source create/update sets `next_sync_due_at` when scheduled.
- [ ] Verification commands pass.
- [ ] Traceability: FR-038, FR-039, FR-040 → this task → commit SHA _TBD_.
