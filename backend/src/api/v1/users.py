"""Users router – list, invite, change role, deactivate.

All endpoints live under ``/api/v1/users`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Every endpoint requires ``admin`` role.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from src.core.deps import get_current_user, require_role
from src.models.user import User, UserRole
from src.schemas.user import (
    InvitationCreateRequest,
    RoleChangeRequest,
    UserListResponse,
    UserResponse,
)
from src.services.source_permission_service import SourcePermissionService
from src.services.user_service import UserService

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

AdminOnly = require_role(UserRole.admin)


def _get_permission_service() -> SourcePermissionService:
    """Resolve :class:`SourcePermissionService` from the DI container."""
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_permission_service()


def _get_user_service() -> UserService:
    """Resolve :class:`UserService` from the DI container.

    Uses a lazy import so that the module can be loaded without triggering
    the full container wiring (helpful for unit tests).
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.user_service()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=UserListResponse)
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
) -> UserListResponse:
    """Return a paginated list of active users."""
    users, total = await user_svc.list_users(admin, limit=limit, offset=offset)
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InvitationCreateRequest,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
) -> dict[str, str]:
    """Send an invitation email to a new user."""
    await user_svc.invite(admin, body.email, body.role)
    return {"detail": "Invitation sent"}


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: UUID,
    body: RoleChangeRequest,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
) -> UserResponse:
    """Change a user's role."""
    updated = await user_svc.change_role(admin, user_id, body.role)
    return UserResponse.model_validate(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
) -> None:
    """Soft-deactivate a user and revoke their refresh tokens."""
    await user_svc.deactivate_user(admin, user_id)


@router.get(
    "/me/sources",
    response_model=list[UUID],
    summary="List source IDs accessible to the current user",
)
async def list_my_sources(
    current_user: User = Depends(get_current_user),
    svc: SourcePermissionService = Depends(_get_permission_service),
) -> list[UUID]:
    """Return the IDs of all sources the authenticated user may access."""
    return await svc.list_for_user(current_user.id)
