"""Source permission endpoints (FR-019 access-control API).

Endpoints live under ``/api/v1/sources`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Admin-only: grant, revoke, list-for-source.
Any authenticated user: (me/sources lives in users router).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.core.deps import require_role
from src.core.exceptions import ConflictError, NotFoundError
from src.models.user import User, UserRole
from src.services.source_permission_service import SourcePermissionService

router = APIRouter()


# ------------------------------------------------------------------
# Schemas (local — small enough to keep inline)
# ------------------------------------------------------------------


class GrantPermissionRequest(BaseModel):
    user_id: uuid.UUID


class PermissionListResponse(BaseModel):
    user_ids: list[uuid.UUID]


# ------------------------------------------------------------------
# Dependency helpers
# ------------------------------------------------------------------

AdminOnly = require_role(UserRole.admin)


def _get_permission_service() -> SourcePermissionService:
    """Resolve :class:`SourcePermissionService` from the DI container."""
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_permission_service()


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
    _admin: User = Depends(AdminOnly),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> None:
    """Grant *body.user_id* access to *source_id*."""
    try:
        await svc.grant(source_id=source_id, user_id=body.user_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{source_id}/permissions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a user's access to a source (admin only)",
)
async def revoke_permission(
    source_id: uuid.UUID,
    user_id: uuid.UUID,
    _admin: User = Depends(AdminOnly),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> None:
    """Revoke *user_id*'s access to *source_id*."""
    try:
        await svc.revoke(source_id=source_id, user_id=user_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{source_id}/permissions",
    response_model=PermissionListResponse,
    summary="List all users that have access to a source (admin only)",
)
async def list_permissions_for_source(
    source_id: uuid.UUID,
    _admin: User = Depends(AdminOnly),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> PermissionListResponse:
    """Return all user_ids that have been granted access to *source_id*."""
    user_ids = await svc.list_for_source(source_id)
    return PermissionListResponse(user_ids=user_ids)
