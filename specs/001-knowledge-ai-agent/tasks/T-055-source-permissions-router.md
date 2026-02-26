# T-055 — Source Permissions FastAPI Router

## Context
```
Python 3.12 | FastAPI · dependency-injector
RBAC: admin-only grant/revoke/list; any authenticated user for /users/me/sources
RFC 7807 error responses
FR-019: enforce permission checks at API boundary
```

## Goal
Expose the `SourcePermissionService` over HTTP.  Four endpoints:
- Admin writes permission rows (grant / revoke).
- Admin reads who has access to a source.
- Any user reads which sources they may access.

---

## File 1 — `app/api/v1/source_permissions.py`

```python
"""Source permission endpoints (FR-019 access-control API)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import get_current_admin_user, get_current_user
from app.containers import ApplicationContainer
from app.core.exceptions import ConflictException, NotFoundException
from app.models.user import User
from app.services.source_permission_service import SourcePermissionService

router = APIRouter(prefix="/sources", tags=["source-permissions"])


# ------------------------------------------------------------------
# Schemas (local — small enough to keep inline)
# ------------------------------------------------------------------
class GrantPermissionRequest(BaseModel):
    user_id: uuid.UUID


class PermissionListResponse(BaseModel):
    user_ids: list[uuid.UUID]


# ------------------------------------------------------------------
# Dependency helper
# ------------------------------------------------------------------
def _get_permission_service(request: Request) -> SourcePermissionService:
    container: ApplicationContainer = request.app.state.container
    return container.source_permission_service()


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
@router.post(
    "/{source_id}/permissions",
    status_code=status.HTTP_201_CREATED,
    summary="Grant a user access to a source (admin only)",
)
async def grant_permission(
    source_id: uuid.UUID,
    body: GrantPermissionRequest,
    _admin: User = Depends(get_current_admin_user),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> None:
    try:
        await svc.grant(source_id=source_id, user_id=body.user_id)
    except NotFoundException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictException as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.delete(
    "/{source_id}/permissions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a user's access to a source (admin only)",
)
async def revoke_permission(
    source_id: uuid.UUID,
    user_id: uuid.UUID,
    _admin: User = Depends(get_current_admin_user),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> None:
    try:
        await svc.revoke(source_id=source_id, user_id=user_id)
    except NotFoundException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{source_id}/permissions",
    response_model=PermissionListResponse,
    summary="List all users that have access to a source (admin only)",
)
async def list_permissions_for_source(
    source_id: uuid.UUID,
    _admin: User = Depends(get_current_admin_user),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> PermissionListResponse:
    user_ids = await svc.list_for_source(source_id)
    return PermissionListResponse(user_ids=user_ids)
```

---

## File 2 — `app/api/v1/users.py` (patch — add me/sources endpoint)

```python
# Add this endpoint to the existing users router:

@router.get(
    "/me/sources",
    response_model=list[uuid.UUID],
    summary="List source IDs accessible to the current user",
)
async def list_my_sources(
    current_user: User = Depends(get_current_user),
    request: Request = None,
) -> list[uuid.UUID]:
    container: ApplicationContainer = request.app.state.container
    svc: SourcePermissionService = container.source_permission_service()
    return await svc.list_for_user(current_user.id)
```

---

## File 3 — `app/api/v1/__init__.py` (patch)

```python
# Add after sources router include:
from app.api.v1.source_permissions import router as source_permissions_router

api_router.include_router(source_permissions_router)
```

---

## Acceptance Criteria

1. `POST /api/v1/sources/{id}/permissions` returns 201 on success; requires admin JWT.
2. `POST` returns 404 when source or user not found.
3. `POST` returns 409 when permission already exists.
4. `DELETE /api/v1/sources/{id}/permissions/{user_id}` returns 204; requires admin JWT.
5. `DELETE` returns 404 when permission row not found.
6. `GET /api/v1/sources/{id}/permissions` returns 200 `{"user_ids": [...]}`.
7. `GET /api/v1/users/me/sources` returns 200 list of UUID strings for the caller.
8. All four endpoints return RFC 7807 Problem Details on error.
9. Non-admin JWT on admin endpoints returns 403.
