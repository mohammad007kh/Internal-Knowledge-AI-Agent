# T-044 — Sources FastAPI Router

## Context
```
Python 3.12 | FastAPI · dependency-injector · JWT RBAC
RFC 7807 error responses | FR-019: per-user source isolation | FR-020: config never in response
```

## Goal
Implement the `/api/v1/sources` REST router with full CRUD + test-connection endpoint. Admin users see all sources; regular users see only their own. All responses use `SourceResponse` / `PaginatedSources` — never `config_encrypted`.

---

## File — `app/api/v1/sources.py`

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.api.dependencies.auth import get_current_user, require_admin
from app.api.dependencies.services import get_source_service
from app.models.user import User
from app.schemas.source import (
    PaginatedSources,
    SourceCreate,
    SourceListItem,
    SourceResponse,
    SourceUpdate,
    TestConnectionResponse,
)
from app.services.source_service import SourceService

router = APIRouter(prefix="/sources", tags=["sources"])


# ------------------------------------------------------------------ #
# Create
# ------------------------------------------------------------------ #

@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new source",
)
async def create_source(
    payload: SourceCreate,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> SourceResponse:
    """
    Create a source owned by the authenticated user.
    Connection config is Fernet-encrypted before persistence.
    """
    source = await service.create_source(payload, owner_id=current_user.id)
    return SourceResponse.model_validate(source)


# ------------------------------------------------------------------ #
# List
# ------------------------------------------------------------------ #

@router.get(
    "",
    response_model=PaginatedSources,
    summary="List sources",
)
async def list_sources(
    offset: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> PaginatedSources:
    """
    Admins receive all active sources.
    Regular users receive only their own sources (active + inactive).
    """
    if current_user.role == "admin":
        items, total = await service.list_all_active_sources(skip=offset, limit=limit)
    else:
        items, total = await service.list_sources_for_owner(
            owner_id=current_user.id, skip=offset, limit=limit
        )
    return PaginatedSources(
        items=[SourceListItem.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ------------------------------------------------------------------ #
# Read
# ------------------------------------------------------------------ #

@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get a single source",
)
async def get_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> SourceResponse:
    """
    Returns the source if the caller is its owner or an admin.
    Raises 404 if the source does not exist, 403 if unauthorized.
    """
    source = await service.get_source(source_id)  # raises NotFoundError → 404
    _assert_ownership_or_admin(source.owner_id, current_user)
    return SourceResponse.model_validate(source)


# ------------------------------------------------------------------ #
# Update
# ------------------------------------------------------------------ #

@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Partially update a source",
)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> SourceResponse:
    """
    Updates only the provided fields.
    If `config` is included, it is re-encrypted before persistence.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    updated = await service.update_source(source_id, payload)
    return SourceResponse.model_validate(updated)


# ------------------------------------------------------------------ #
# Delete (soft)
# ------------------------------------------------------------------ #

@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a source",
)
async def delete_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> Response:
    """
    Sets `is_active = False`.  The source record is retained for audit purposes.
    Raises 404 if the source does not exist.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    await service.delete_source(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ #
# Test connection
# ------------------------------------------------------------------ #

@router.post(
    "/{source_id}/test-connection",
    response_model=TestConnectionResponse,
    summary="Test connector reachability",
)
async def test_connection(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(get_source_service),
) -> TestConnectionResponse:
    """
    Attempts a live connection using the stored (decrypted) config.
    Always returns `{"success": bool}` — never raises 5xx for connectivity failures.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    ok = await service.test_connection(source_id)
    return TestConnectionResponse(
        success=ok,
        message="" if ok else "Connection attempt failed — check credentials and network.",
    )


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _assert_ownership_or_admin(owner_id: uuid.UUID, user: User) -> None:
    if user.role != "admin" and user.id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "https://httpstatuses.com/403",
                "title": "Forbidden",
                "status": 403,
                "detail": "You are not authorised to access this source.",
            },
        )
```

---

## Wire Router — `app/api/v1/__init__.py` (or `app/api/v1/router.py`)

```python
# append to existing api_v1_router includes:
from app.api.v1.sources import router as sources_router

api_v1_router.include_router(sources_router)
```

---

## DI Provider — `app/api/dependencies/services.py`

```python
# append:
from app.containers import ApplicationContainer

def get_source_service() -> SourceService:
    container: ApplicationContainer = _get_container()
    return container.source_service()
```

---

## DI Container — `app/containers.py`

```python
# Inside ApplicationContainer, add:
source_repository: providers.Factory = providers.Factory(
    SourceRepository,
    session_factory=db.provided.session,
)
source_service: providers.Factory = providers.Factory(
    SourceService,
    repository=source_repository,
    settings=config,
)
```

---

## Acceptance Criteria

- [ ] `POST /api/v1/sources` → 201 with `SourceResponse` (no `config`/`config_encrypted`)
- [ ] `GET /api/v1/sources` admin call returns all active sources; user call returns own only
- [ ] `GET /api/v1/sources/{id}` raises 403 when non-owner non-admin requests another user's source
- [ ] `DELETE /api/v1/sources/{id}` returns 204, source `is_active` becomes `False`
- [ ] `POST /api/v1/sources/{id}/test-connection` returns `{"success": false}` (not 5xx) on connectivity failure
- [ ] All 404 paths return RFC 7807 Problem Details from the existing error handler
