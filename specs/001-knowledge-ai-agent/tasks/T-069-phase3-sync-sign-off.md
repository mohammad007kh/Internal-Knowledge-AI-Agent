# T-069 â€” Phase 3 Sync Sign-Off

**Status:** Done

## Context
```
Phase 3 deliverables: T-060â€“T-068
Docker Compose 9 services
GitHub Actions CI
coverage â‰¥ 80%
All FR-030â€“FR-035 acceptance criteria
```

## Goal
Final acceptance checklist for **Phase 3 â€” Background Sync & Ingestion Pipeline**.  
All items must be âœ… before work on Phase 4 (LangGraph) begins.

---

## Deliverables Created in Phase 3

| Task | Deliverable |
|---|---|
| T-060 | `SyncJob` ORM model + Alembic migration `0008_sync_jobs.py` |
| T-061 | `SyncJobRepository`, `SyncJobService`, `SyncJobResponse` schema |
| T-062 | `ChunkingService` with `RecursiveCharacterTextSplitter`, `ChunkData` dataclass |
| T-063 | `EmbeddingService` (AsyncOpenAI, tenacity 3-retry, `EmbeddingDimensionError`) |
| T-064 | Celery `sync_source` task â€” full pipeline, `_sanitise`, Langfuse tracing |
| T-065 | Beat schedule (`*/30` min fan-out), `trigger_all_syncs` task, `worker`/`beat` Compose services |
| T-066 | Sync Jobs API router (`POST /sync`, `GET /sync-jobs/{id}`, `GET /sources/{id}/sync-jobs`) |
| T-067 | `SyncStatusBadge`, `TriggerSyncButton`, `useSyncJob` polling hook |
| T-068 | Integration tests â€” happy path, failure, retry, API |

---

## 1  FR Acceptance Checklist

### FR-030 â€” Ingest pipeline

- [ ] `sync_source` task calls connector â†’ chunks â†’ embeddings â†’ persists `Document` + `Chunk` rows
- [ ] `POST /sources/{id}/sync` returns 202 + `SyncJobResponse` with `status="pending"`
- [ ] `TriggerSyncButton` POSTs and shows Sonner toast

### FR-031 â€” Vectors persisted in pgvector

- [ ] `Chunk.embedding` column is `VECTOR(1536)` with HNSW index (`m=16, ef_construction=64`)
- [ ] Integration test asserts `chunk.embedding is not None` for every created chunk
- [ ] Migration `0008` applied cleanly on a fresh DB with no data

### FR-033 â€” Periodic sync & retry

- [ ] Beat schedule: `"sync-all-sources"` fires `tasks.trigger_all_syncs` every 30 min
- [ ] `beat` Compose service has `deploy.replicas: 1`
- [ ] `sync_source` task has `max_retries=3` with `countdown=2**retries` backoff
- [ ] `task_acks_late=True`, `task_reject_on_worker_lost=True` in `celeryconfig.py`

### FR-035 â€” File size limit

- [ ] `FileUploadConnector.fetch_documents()` checks file size against `app_config.yaml` limit (default 50 MB)
- [ ] Oversized upload raises `FileTooLargeError` â€” maps to 422 in the API

### FR-019 â€” Access control

- [ ] `POST /sources/{id}/sync` requires `role=="admin"` â†’ 403 for non-admin
- [ ] `sync_source` task reads `source.owner_id` and does not publish data to other users

### FR-020 â€” No plaintext connection strings

- [ ] `_sanitise()` strips `://user:pass@` patterns from all error messages
- [ ] Unit test `test_strips_credentials` passes
- [ ] `SyncJobResponse.error_message` never contains raw credentials

---

## 2  Architecture Invariants

| Invariant | Verified by |
|---|---|
| Celery broker/backend = Redis | `app/tasks/__init__.py` uses `_settings.redis.url` |
| Beat replicas exactly 1 | `docker-compose.yml` `deploy.replicas: 1` |
| No PII in Langfuse spans | `_sanitise()` applied before any span attribute write |
| HNSW index on `chunks.embedding` | Migration `0008` or dedicated index migration |
| Alembic chain unbroken | `0001 â†’ 0002 â†’ â€¦ â†’ 0008` (no gaps, no double heads) |

---

## 3  Manual QA Steps

```bash
# 1. Fresh-stack smoke test
docker compose down -v
docker compose up -d --build
docker compose exec backend alembic upgrade head
# Expected: 8 migrations applied, no errors

# 2. Seed a source and trigger sync
docker compose exec backend python -c "
from app.tasks.sync_source import sync_source
sync_source.apply(args=['<source_uuid>'])
"
# Expected: SyncJob row created with status=success

# 3. Confirm beat fires
docker compose logs beat | grep "trigger_all_syncs"
# Expected: log line within 30 min of stack start

# 4. Confirm pgvector index
docker compose exec db psql -U postgres -d knowledge_ai \
  -c "\d chunks"
# Expected: 'embedding' column type vector(1536), HNSW index listed

# 5. Duplicate beat prevention
docker compose up -d --scale beat=2 2>&1 | grep -i "replica"
# Expected: warning or refusal â€” or only 1 container actually runs
```

---

## 4  Test Coverage Gate

Run full suite and assert coverage:

```bash
pytest tests/ --cov=app --cov-report=term-missing --cov-fail-under=80
```

Expected modules â‰¥ target:

| Module | Target |
|---|---|
| `app/tasks/sync_source.py` | â‰¥ 85% |
| `app/services/sync_job_service.py` | â‰¥ 90% |
| `app/services/chunking_service.py` | â‰¥ 90% |
| `app/services/embedding_service.py` | â‰¥ 85% |
| `app/api/v1/sync_jobs.py` | â‰¥ 85% |

---

## 5  Phase 3 Commit

Once all checkboxes are ticked:

```bash
git add specs/001-knowledge-ai-agent/tasks/T-060-*.md \
        specs/001-knowledge-ai-agent/tasks/T-061-*.md \
        specs/001-knowledge-ai-agent/tasks/T-062-*.md \
        specs/001-knowledge-ai-agent/tasks/T-063-*.md \
        specs/001-knowledge-ai-agent/tasks/T-064-*.md \
        specs/001-knowledge-ai-agent/tasks/T-065-*.md \
        specs/001-knowledge-ai-agent/tasks/T-066-*.md \
        specs/001-knowledge-ai-agent/tasks/T-067-*.md \
        specs/001-knowledge-ai-agent/tasks/T-068-*.md \
        specs/001-knowledge-ai-agent/tasks/T-069-*.md

git commit -m "feat(specs): Phase 3 â€” background sync & ingestion pipeline (T-060â€“T-069)"
```

---

## 6  Phase 4 Entry Condition

Phase 4 (LangGraph retrieval & chat) begins **only after** this checklist is fully signed off.

| Phase 4 first task | T-070 â€” LangGraph `AgentState` + pipeline scaffold |
|---|---|
| Branch | `001-knowledge-ai-agent` (same) |
| Estimated tasks | T-070 â€“ T-079 (10 tasks) |
