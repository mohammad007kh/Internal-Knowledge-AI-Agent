# T-028 â€” Users FastAPI Router (CRUD + Invitation)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-028 |
| **Title** | Users FastAPI Router â€” list, invite, change role, deactivate |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Backend / API |
| **Depends on** | T-015, T-023, T-024, T-027, T-029 |
| **Blocks** | T-030, T-036 |
| **Est. complexity** | M |

---

## Goal
Implement the 4-endpoint users router â€” all admin-only â€” plus the companion `UserService.invite_user()` that creates an `Invitation` record and returns the raw invitation token.

---

## API Contract

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/users` | Admin | List all users (paginated, offset-based) |
| `POST` | `/api/v1/users/invitations` | Admin | Create invitation and send email |
| `PATCH` | `/api/v1/users/{user_id}/role` | Admin | Change user role |
| `DELETE` | `/api/v1/users/{user_id}` | Admin | Soft-deactivate user |

---

## Deliverables

### 1. `app/services/user_service.py` â€” additional methods
Extend the existing `UserService` (T-023 established the repo-level):

```python
class UserService:
    async def list_users(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[User], int]:
        """Returns (users, total_count) for pagination."""
        return await self._user_repo.list_paginated(limit=limit, offset=offset)

    async def invite_user(self, email: str, role: UserRole) -> str:
        """
        Create an invitation for email.

        - Ensures email is not already in use (active user OR pending invitation)
        - Creates Invitation record with 7-day TTL
        - Returns the raw invitation token (router will pass to EmailService)
        """
        existing = await self._user_repo.get_by_email(email)
        if existing:
            raise ConflictError(f"An account with email {email!r} already exists")

        pending = await self._invitation_repo.get_active_by_email(email)
        if pending:
            # Revoke old invitation, issue fresh one (re-invite flow)
            await self._invitation_repo.revoke(pending.id)

        import secrets
        from datetime import datetime, timezone, timedelta
        raw_token = secrets.token_urlsafe(32)
        await self._invitation_repo.create(
            email=email,
            role=role,
            raw_token=raw_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        return raw_token

    async def change_role(self, user_id: UUID, new_role: UserRole) -> User:
        user = await self._user_repo.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        return await self._user_repo.update(user_id, {"role": new_role})

    async def deactivate(self, user_id: UUID, *, acting_admin_id: UUID) -> None:
        """Soft-deactivate. Admin cannot deactivate themselves."""
        if user_id == acting_admin_id:
            raise ForbiddenError("You cannot deactivate your own account")
        user = await self._user_repo.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        await self._user_repo.update(user_id, {"is_active": False})
        # Revoke all active refresh tokens so the session ends immediately
        from app.repositories.refresh_token_repository import RefreshTokenRepository
        await RefreshTokenRepository(self._db).revoke_all_for_user(user_id)

    async def accept_invitation(
        self, invitation_token: str, password: str
    ) -> User:
        """
        Called by AuthService.accept_invitation().

        Validates token, creates User, marks invitation as accepted.
        """
        invitation = await self._invitation_repo.get_active_by_token(invitation_token)
        if not invitation:
            raise NotFoundError("Invitation not found or expired")

        if invitation.accepted_at is not None:
            raise ConflictError("Invitation already accepted")

        hashed = self._password_svc.hash_password(password)
        user = await self._user_repo.create(
            email=invitation.email,
            hashed_password=hashed,
            role=invitation.role,
        )
        await self._invitation_repo.mark_accepted(invitation.id)
        return user
```

---

### 2. `app/api/v1/users.py`
```python
from uuid import UUID
from fastapi import APIRouter, Depends, status, Query

from app.containers import get_user_service, get_email_service
from app.core.deps import require_role
from app.models.user import User, UserRole
from app.schemas.user import (
    UserListResponse, UserResponse, InvitationCreateRequest
)
from app.services.user_service import UserService
from app.services.email_service import EmailService

router = APIRouter(prefix="/users", tags=["users"])
AdminOnly = require_role(UserRole.admin)


@router.get("", response_model=UserListResponse)
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_svc: UserService = Depends(get_user_service),
    _admin: User = Depends(AdminOnly),
):
    users, total = await user_svc.list_users(limit=limit, offset=offset)
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,   # { "detail": "Invitation sent" }
)
async def invite_user(
    body: InvitationCreateRequest,
    user_svc: UserService = Depends(get_user_service),
    email_svc: EmailService = Depends(get_email_service),
    _admin: User = Depends(AdminOnly),
):
    raw_token = await user_svc.invite_user(body.email, body.role)
    await email_svc.send_invitation(body.email, raw_token)
    return {"detail": "Invitation sent"}


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: UUID,
    body: dict,   # { "role": "user" | "admin" }
    user_svc: UserService = Depends(get_user_service),
    _admin: User = Depends(AdminOnly),
):
    new_role = UserRole(body.get("role"))
    user = await user_svc.change_role(user_id, new_role)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    user_svc: UserService = Depends(get_user_service),
    admin: User = Depends(AdminOnly),
):
    await user_svc.deactivate(user_id, acting_admin_id=admin.id)
```

### 3. Register in `app/api/v1/router.py`
```python
from app.api.v1.users import router as users_router
api_v1_router.include_router(users_router)  # prefix="/users" already on router
```

---

### 4. Pydantic schemas (add to `app/schemas/user.py` from T-024)
```python
class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int

class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.user
```

---

## Acceptance Criteria
- [ ] `GET /users` returns paginated list with `total`, `limit`, `offset`; requires admin token
- [ ] `GET /users` with non-admin token â†’ `403`
- [ ] `POST /users/invitations` with valid email â†’ `201 {"detail": "Invitation sent"}`; `EmailService.send_invitation` called with raw token
- [ ] `POST /users/invitations` with duplicate email (existing user) â†’ `409`
- [ ] `POST /users/invitations` with duplicate pending invitation â†’ revokes old, creates new (re-invite)
- [ ] `PATCH /users/{id}/role` updates role and returns updated `UserResponse`
- [ ] `PATCH /users/{id}/role` with invalid role value â†’ `422`
- [ ] `DELETE /users/{id}` soft-deactivates user; revokes all active refresh tokens
- [ ] `DELETE /users/{id}` where `id == acting_admin_id` â†’ `403`
- [ ] `DELETE /users/{id}` for non-existent id â†’ `404`
- [ ] Router registered in `api_v1_router`

---

## FR References
| FR | Requirement |
|---|---|
| FR-021 | Invitations as sole path to new accounts |
| FR-022 | Admin can deactivate users |
