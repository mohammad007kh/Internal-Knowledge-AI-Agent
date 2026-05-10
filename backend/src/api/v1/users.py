"""Users router – list, invite, change role, deactivate.

All endpoints live under ``/api/v1/users`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Every endpoint requires ``admin`` role.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user, require_role
from src.models.user import User, UserRole
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.user_repository import UserRepository
from src.schemas.invitation import InvitationListResponse, InvitationPublic
from src.schemas.user import (
    InvitationCreateRequest,
    RoleChangeRequest,
    UpdateUserRequest,
    UserListResponse,
    UserPublic,
    UserResponse,
    UserUpdateRequest,
)
from src.services.audit_service import emit_audit
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
    request: Request,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Send an invitation email to a new user."""
    invitation, _raw_token = await user_svc.invite(admin, body.email, body.role)
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=admin.id,
        action="user.invite",
        resource_type="user",
        resource_id=invitation.id,
        request=request,
        metadata={"email": body.email, "role": body.role.value},
    )
    await db.commit()
    return {"detail": "Invitation sent"}


@router.get(
    "/invitations",
    response_model=InvitationListResponse,
    summary="List pending invitations",
)
async def list_invitations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> InvitationListResponse:
    """Return paginated pending (not accepted, not expired) invitations. Admin-only."""
    repo = InvitationRepository(db)
    items, total = await repo.list_pending(limit=limit, offset=offset)
    return InvitationListResponse(
        items=[InvitationPublic.from_orm_row(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a pending invitation",
)
async def revoke_invitation(
    invitation_id: UUID,
    _admin: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete a pending invitation. Admin-only.

    Returns 404 if the invitation does not exist and 409 if it has already
    been accepted (already-accepted invitations are retained for audit).
    """
    repo = InvitationRepository(db)
    invite = await repo.get_by_id(invitation_id)
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "title": "Invitation not found",
                "status": status.HTTP_404_NOT_FOUND,
                "type": "not_found",
            },
        )
    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "title": "Cannot revoke accepted invitation",
                "status": status.HTTP_409_CONFLICT,
                "type": "conflict",
            },
        )
    await repo.revoke(invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/lookup", response_model=UserResponse, summary="Look up a user by email")
async def lookup_user(
    email: str = Query(..., description="Email address to look up"),
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return id, email, full_name for a user matching *email*. Admin-only."""
    repo = UserRepository(db)
    user = await repo.get_by_email(email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse.model_validate(user)


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get the current user's profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    """Return the profile of the authenticated user."""
    return UserPublic.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserPublic,
    summary="Update the current user's profile",
)
async def update_me(
    body: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPublic:
    """Partial update of the authenticated user's own profile.

    Password changes require ``current_password`` for re-authentication.
    """
    from src.core.container import Container  # noqa: PLC0415

    new_hash: str | None = None
    if body.new_password:
        password_service = Container.password_service()
        if body.current_password is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "title": "current_password required",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "type": "validation_error",
                },
            )
        if not password_service.verify_password(
            body.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "title": "Invalid current password",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "type": "invalid_credentials",
                },
            )
        try:
            password_service.validate_password_policy(body.new_password)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "title": "Password policy violation",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "type": "validation_error",
                    "detail": str(exc),
                },
            ) from exc
        new_hash = password_service.hash_password(body.new_password)

    user_repo = UserRepository(db)
    updated = await user_repo.update_me(
        user_id=current_user.id,
        full_name=body.full_name,
        show_citations_preference=body.show_citations_preference,
        new_password_hash=new_hash,
    )
    return UserPublic.model_validate(updated)


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


@router.get("/{user_id}", response_model=UserResponse, summary="Look up a user by ID")
async def get_user_by_id(
    user_id: UUID,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return user details for a given user ID. Admin-only."""
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: UUID,
    body: RoleChangeRequest,
    request: Request,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Change a user's role."""
    from src.repositories.user_repository import UserRepository  # noqa: PLC0415

    target_before = await UserRepository(db).get_by_id(user_id)
    old_role = target_before.role.value if target_before is not None else None
    updated = await user_svc.change_role(admin, user_id, body.role)
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=admin.id,
        action="user.role_change",
        resource_type="user",
        resource_id=updated.id,
        request=request,
        metadata={"from": old_role, "to": body.role.value},
    )
    await db.commit()
    return UserResponse.model_validate(updated)


@router.post(
    "/{user_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin-trigger password reset for a user",
)
async def admin_reset_password(
    user_id: UUID,
    request: Request,
    admin: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate a password-reset token for *user_id* and send the user the
    standard reset email.

    Reuses :meth:`AuthService.request_password_reset` so the resulting flow
    (token format, expiry, single-use semantics) is identical to a user-
    initiated forgot-password request. The raw token is never returned in
    the response — emailing it to the user is the contract.

    The frontend admin user-detail page (``/admin/users/[id]``) calls this.
    Returns 204 on success, 404 if the user doesn't exist.
    """
    from src.core.container import Container  # noqa: PLC0415

    target = await UserRepository(db).get_by_id(user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://httpstatuses.com/404",
                "title": "Not Found",
                "status": 404,
                "detail": "User not found.",
            },
        )

    auth_svc = Container.auth_service()
    # Reset is best-effort against the user's email address. The service
    # silently skips inactive users — that's intentional (no enumeration).
    await auth_svc.request_password_reset(target.email)

    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=admin.id,
        action="user.password_reset",
        resource_type="user",
        resource_id=target.id,
        request=request,
        metadata={"email": target.email},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    request: Request,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-deactivate a user and revoke their refresh tokens."""
    await user_svc.deactivate_user(admin, user_id)
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=admin.id,
        action="user.deactivate",
        resource_type="user",
        resource_id=user_id,
        request=request,
        metadata={},
    )
    await db.commit()


@router.patch("/{user_id}", response_model=UserResponse, summary="Activate or deactivate a user")
async def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    admin: User = Depends(AdminOnly),
    user_svc: UserService = Depends(_get_user_service),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Toggle ``is_active`` for a user. Admin-only."""
    repo = UserRepository(db)
    if body.is_active is not None:
        updated = await repo.set_active(user_id, body.is_active)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        await db.commit()
        return UserResponse.model_validate(updated)
    # No-op: return current user
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse.model_validate(user)
