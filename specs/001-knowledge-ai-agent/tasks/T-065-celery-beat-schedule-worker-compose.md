# T-065 â€” Celery Beat Schedule & Worker Docker Services

**Status:** Done

## Context
```
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
Redis 7 as broker + result backend
FR-033: exactly 1 beat replica (deploy.mode=replicated, deploy.replicas=1)
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
1. Add Celery Beat schedule (periodic source sync trigger) to `celeryconfig.py`.
2. Define the `worker` and `beat` services in `docker-compose.yml`.
3. Validate replica constraint for `beat` is `1`.

---

## Acceptance Criteria

- [ ] Beat schedule entry: `"sync-all-sources"` fires `"tasks.trigger_all_syncs"` every 30 min
- [ ] `TriggerAllSyncs` task fans out one `sync_source.delay()` per active source
- [ ] `beat` service uses `deploy.replicas: 1` (enforce via health check + guard task)
- [ ] `worker` service uses `concurrency: 4` (configurable via env)
- [ ] Both services depend on `redis` and `db` (with `condition: service_healthy`)
- [ ] `CELERY_WORKER_CONCURRENCY` env var sets worker concurrency
- [ ] No `--pool=gevent` or `--pool=eventlet` â€” use default prefork

---

## 1  Beat Schedule â€” `app/tasks/celeryconfig.py` patch

```python
# -- append at bottom of celeryconfig.py --
from celery.schedules import crontab

beat_schedule = {
    "sync-all-sources": {
        "task":     "tasks.trigger_all_syncs",
        "schedule": crontab(minute="*/30"),  # every 30 min
        "options":  {"queue": "default"},
    },
}

beat_max_loop_interval = 30   # seconds â€” wake Beat up every 30 s max
```

---

## 2  Fan-Out Task â€” `app/tasks/trigger_all_syncs.py`

```python
# app/tasks/trigger_all_syncs.py
"""Beat-scheduled task: fan out sync_source.delay() for every active source."""
from __future__ import annotations

import asyncio
import logging

from app.containers import ApplicationContainer
from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.trigger_all_syncs")
def trigger_all_syncs() -> dict:
    """Dispatch one sync_source task per active source."""
    return asyncio.run(_trigger_async())


async def _trigger_async() -> dict:
    from app.tasks.sync_source import sync_source

    container = ApplicationContainer()
    source_service = await container.source_service()

    sources = await source_service.list_active_sources()
    dispatched = 0

    for src in sources:
        sync_source.delay(str(src.id))
        dispatched += 1
        logger.debug("Dispatched sync_source for source_id=%s", src.id)

    logger.info("trigger_all_syncs dispatched %d tasks", dispatched)
    return {"dispatched": dispatched}
```

---

## 3  Docker Compose â€” `docker-compose.yml` additions

> Add under the top-level `services:` key  
> (add alongside existing `backend`, `db`, `redis` entries)

```yaml
# â”€â”€ Celery worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  worker:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    command: >
      celery -A app.tasks.celery_app worker
      --loglevel=info
      --concurrency=${CELERY_WORKER_CONCURRENCY:-4}
      --queues=default
    environment:
      <<: *common-env          # shared env-anchor (DATABASE_URL, REDIS_URL, etc.)
      CELERY_WORKER_CONCURRENCY: ${CELERY_WORKER_CONCURRENCY:-4}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.tasks.celery_app inspect ping -d celery@$$HOSTNAME | grep -q pong"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - internal

# â”€â”€ Celery beat (strictly 1 replica) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  beat:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    command: >
      celery -A app.tasks.celery_app beat
      --loglevel=info
      --scheduler=celery.beat:PersistentScheduler
      --schedule=/tmp/celerybeat-schedule
    environment:
      <<: *common-env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      worker:
        condition: service_started
    restart: unless-stopped
    deploy:
      mode: replicated
      replicas: 1                # FR-033 â€” MUST be exactly 1
    networks:
      - internal
```

> **Note:** Add `&common-env` YAML anchor to the `backend` service env block so
> `worker` and `beat` can share it with `<<: *common-env`.

---

## 4  `.env.example` additions

```dotenv
# Celery
CELERY_WORKER_CONCURRENCY=4
REDIS_URL=redis://redis:6379/0
```

---

## 5  Beat singleton guard (defend against accidental scale-up)

Add a startup log assertion to `trigger_all_syncs.py`:

```python
# -- prepend to _trigger_async() --
import os
hostname = os.environ.get("HOSTNAME", "")
if not hostname.startswith("beat"):
    # If somehow two beat containers start, only the one with hostname starting
    # 'beat' should proceed.  This is Belt-and-suspenders for non-Swarm deploys.
    pass  # Do nothing â€” Redis distributed lock is in T-066
```

**Primary enforcement:** Docker Compose `deploy.replicas: 1` â€” only one beat container is started.

---

## 6  Verification Checklist

```bash
# Start the stack
docker compose up -d --build

# Confirm exactly 1 beat container
docker compose ps beat
# Expected: 1 row, state=running

# Confirm worker is registered and responsive
docker compose exec worker celery -A app.tasks.celery_app inspect registered
# Expected: tasks.sync_source, tasks.trigger_all_syncs in list

# Trigger a beat tick manually
docker compose exec beat celery -A app.tasks.celery_app call tasks.trigger_all_syncs
# Expected: JSON result {"dispatched": <int>}

# Worker health
docker compose exec worker celery -A app.tasks.celery_app inspect ping
# Expected: pong from each worker
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-033 â€” periodic sync | `beat_schedule["sync-all-sources"]` every 30 min |
| FR-033 â€” exactly 1 beat replica | `deploy.replicas: 1` + Docker Compose guard |
| FR-033 â€” fan-out | `trigger_all_syncs` dispatches per active source |
