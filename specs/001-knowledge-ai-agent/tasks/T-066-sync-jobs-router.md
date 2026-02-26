# T-066 — Sync Jobs API Router

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user)
RFC 7807 Problem Details — all non-2xx API responses
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
Structured logging · INFO level · X-Request-ID correlation
```

## Goal
Expose three HTTP endpoints for Sync Job management:

| Method | Path | Auth | Status |
|---|---|---|---|
| `POST` | `/sources/{source_id}/sync` | admin only | 202 Accepted |
| `GET` | `/sync-jobs/{job_id}` | authenticated | 200 |
| `GET` | `/sources/{source_id}/sync-jobs` | admin only | 200 paginated |

---

## Acceptance Criteria

- [ ] `POST /sources/{source_id}/sync` dispatches `sync_source.delay()`, returns `SyncJobResponse` with `status="pending"`
- [ ] `GET /sync-jobs/{job_id}` returns live `SyncJobResponse` (404 if not found)
- [ ] `GET /sources/{source_id}/sync-jobs` returns list sorted `created_at DESC` with `limit`/`offset` pagination
- [ ] Non-admin calls to admin-only routes → 403 RFC 7807
- [ ] Source not found → 404 RFC 7807
- [ ] Router registered at `/api/v1`
- [ ] Rate limit: `POST /sync` no more than 5 per minute per user (via `slowapi` limiter)

---

## 1  `app/api/v1/sync_jobs.py`

```python
# app/api/v1/sync_jobs.py
"""Sync Job endpoints: trigger, status, list."""
from __future__ import annotations

import logging
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_admin_user, get_current_user
from app.containers import ApplicationContainer
from app.core.problem_details import problem
from app.models.user import User
from app.schemas.sync_job import SyncJobListResponse, SyncJobResponse
from app.services.source_service import SourceService
from app.services.sync_job_service import SyncJobService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sync-jobs"])

# ── Trigger sync ──────────────────────────────────────────────────────────

@router.post(
    "/{source_id}/sync",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a sync job for a source (admin only)",
)
@inject
async def trigger_sync(
    source_id: UUID,
    _admin: User = Depends(get_current_admin_user),
    source_svc: SourceService = Depends(Provide[ApplicationContainer.source_service]),
    sync_job_svc: SyncJobService = Depends(Provide[ApplicationContainer.sync_job_service]),
) -> SyncJobResponse:
    source = await source_svc.get_by_id(source_id)
    if source is None:
        raise problem(
            status=404,
            title="Source Not Found",
            detail=f"Source {source_id} does not exist.",
            instance=f"/sources/{source_id}",
        )

    job = await sync_job_svc.create_job(source_id=source_id)

    # Dispatch async — import here to avoid circular at module load
    from app.tasks.sync_source import sync_source  # noqa: PLC0415

    sync_source.delay(str(source_id))
    logger.info(
        "Sync triggered",
        extra={"source_id": str(source_id), "job_id": str(job.id)},
    )
    return SyncJobResponse.model_validate(job)


# ── Get sync job ───────────────────────────────────────────────────────────

dedicated_router = APIRouter(prefix="/sync-jobs", tags=["sync-jobs"])


@dedicated_router.get(
    "/{job_id}",
    response_model=SyncJobResponse,
    summary="Get a sync job by ID",
)
@inject
async def get_sync_job(
    job_id: UUID,
    _user: User = Depends(get_current_user),
    sync_job_svc: SyncJobService = Depends(Provide[ApplicationContainer.sync_job_service]),
) -> SyncJobResponse:
    job = await sync_job_svc.get_job(job_id)
    if job is None:
        raise problem(
            status=404,
            title="Sync Job Not Found",
            detail=f"Sync job {job_id} does not exist.",
            instance=f"/sync-jobs/{job_id}",
        )
    return SyncJobResponse.model_validate(job)


# ── List sync jobs for a source ────────────────────────────────────────────

@router.get(
    "/{source_id}/sync-jobs",
    response_model=SyncJobListResponse,
    summary="List sync jobs for a source (admin only)",
)
@inject
async def list_sync_jobs(
    source_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(get_current_admin_user),
    source_svc: SourceService = Depends(Provide[ApplicationContainer.source_service]),
    sync_job_svc: SyncJobService = Depends(Provide[ApplicationContainer.sync_job_service]),
) -> SyncJobListResponse:
    source = await source_svc.get_by_id(source_id)
    if source is None:
        raise problem(
            status=404,
            title="Source Not Found",
            detail=f"Source {source_id} does not exist.",
            instance=f"/sources/{source_id}",
        )

    jobs = await sync_job_svc.list_for_source(
        source_id=source_id, limit=limit, offset=offset
    )
    return SyncJobListResponse(items=jobs, total=len(jobs), limit=limit, offset=offset)
```

---

## 2  Schema additions — `app/schemas/sync_job.py`

```python
# append to existing sync_job.py

class SyncJobListResponse(BaseModel):
    """Paginated list of sync jobs."""

    items: list[SyncJobResponse]
    total: int
    limit: int
    offset: int
```

---

## 3  Register routers — `app/api/v1/__init__.py`

```python
# append to existing router inclusions
from app.api.v1.sync_jobs import dedicated_router as sync_jobs_dedicated_router
from app.api.v1.sync_jobs import router as sync_jobs_router

api_router.include_router(sync_jobs_router)          # /sources/{source_id}/sync[/-jobs]
api_router.include_router(sync_jobs_dedicated_router)  # /sync-jobs/{job_id}
```

---

## 4  Problem Details helper — `app/core/problem_details.py` (if not yet exists)

```python
# app/core/problem_details.py
"""RFC 7807 Problem Details factory used throughout the API layer."""
from fastapi import HTTPException


def problem(
    *,
    status: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
    instance: str | None = None,
) -> HTTPException:
    """Return an HTTPException whose detail is an RFC 7807 dict."""
    body: dict = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    return HTTPException(status_code=status, detail=body)
```

---

## 5  `app/api/deps.py` additions (if admin guard not yet present)

```python
async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: requires the current user to have role='admin'."""
    if current_user.role != "admin":
        raise problem(
            status=403,
            title="Forbidden",
            detail="Administrator role required.",
        )
    return current_user
```

---

## 6  Error Scenarios

| Scenario | HTTP | RFC 7807 title |
|---|---|---|
| Source not found | 404 | `Source Not Found` |
| Job not found | 404 | `Sync Job Not Found` |
| Non-admin triggers sync | 403 | `Forbidden` |
| Non-admin lists jobs | 403 | `Forbidden` |
| Source exists but is already syncing | 202 | *(still accepted; duplicate handled at worker)* |

---

## 7  Tests (outline) — `tests/integration/test_sync_jobs_router.py`

```python
async def test_trigger_sync_admin_202(client, admin_token, db_source):
    resp = await client.post(f"/api/v1/sources/{db_source.id}/sync",
                              headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"


async def test_trigger_sync_non_admin_403(client, user_token, db_source):
    resp = await client.post(f"/api/v1/sources/{db_source.id}/sync",
                              headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 403


async def test_get_sync_job(client, user_token, db_job):
    resp = await client.get(f"/api/v1/sync-jobs/{db_job.id}",
                             headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(db_job.id)


async def test_list_sync_jobs(client, admin_token, db_source, db_jobs):
    resp = await client.get(f"/api/v1/sources/{db_source.id}/sync-jobs",
                             headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert "items" in resp.json()
```

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-030 — trigger ingestion | `POST /sources/{id}/sync` |
| FR-033 — observe job status | `GET /sync-jobs/{id}` |
| FR-019 — admin-only trigger | `get_current_admin_user` dep |
| RFC 7807 — error format | `problem()` helper |
