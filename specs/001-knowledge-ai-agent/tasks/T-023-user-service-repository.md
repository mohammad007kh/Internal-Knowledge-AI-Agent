---
id: T-023
title: User Repository + User Service (Business Logic Layer)
status: Not Started
created: 2026-02-25
phase: Phase 1 — Auth & User Management
user_story: US3, US4, US5
requirements: [FR-AUTH-1, FR-AUTH-2, FR-USER-1, FR-USER-2]
priority: P1
depends_on: [T-013, T-021, T-022]
blocks: [T-025, T-026]
estimated_effort: 2h
---

## Goal

Implement `UserRepository` (data layer) and `UserService` (business logic layer) for all user-related operations. These are the only classes that read/write the `users` and `invitations` tables.

---

## Acceptance Criteria

**UserRepository**
- [ ] `get_by_email(email)` — case-insensitive lookup, excludes soft-deleted
- [ ] `get_by_id(id)` — inherited from `BaseRepository`
- [ ] `list_active(limit, offset)` — only `is_active=True` and non-deleted
- [ ] `create(email, hashed_password, full_name, role)` → `User`
- [ ] `soft_delete(id)` — inherited
- [ ] `set_active(id, is_active)` → updates `is_active`

**InvitationRepository**
- [ ] `get_by_token(token)` → `Invitation | None`
- [ ] `create(email, role, invited_by, expires_at)` → `Invitation`
- [ ] `mark_accepted(token)` → sets `accepted_at = now()`

**UserService**
- [ ] `register(email, password, full_name) -> User` — raises `ConflictError` if email exists; hashes password; creates user
- [ ] `invite(admin_user, email, role) -> Invitation` — raises `ConflictError` if active user/invitation exists; creates invitation; **sends email** via `EmailService.send_invitation` (stub in this task, real in T-035)
- [ ] `accept_invitation(token, full_name, password) -> User` — validates token not expired/accepted; creates user; marks invitation accepted
- [ ] `deactivate_user(admin, target_id)` — admin only; raises `ForbiddenError` if not admin
- [ ] `list_users(admin, limit, offset)` — admin only

---

## Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/repositories/user_repository.py` | DB access for users |
| `backend/src/repositories/invitation_repository.py` | DB access for invitations |
| `backend/src/services/user_service.py` | Business logic |
| `backend/tests/unit/test_user_service.py` | Unit tests with mocked repositories |

---

## Implementation Sketch

### `backend/src/services/user_service.py`

```python
from datetime import datetime, timedelta, timezone
import uuid
from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from src.models.user import User, Invitation, UserRole
from src.services.password_service import PasswordService
from src.repositories.user_repository import UserRepository
from src.repositories.invitation_repository import InvitationRepository

INVITATION_EXPIRY_DAYS = 7


class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        invitation_repo: InvitationRepository,
        password_service: PasswordService,
    ) -> None:
        self._users = user_repo
        self._invitations = invitation_repo
        self._pw = password_service

    async def register(self, email: str, password: str, full_name: str) -> User:
        self._pw.validate_password_policy(password)
        if await self._users.get_by_email(email):
            raise ConflictError(f"Email '{email}' is already registered.")
        hashed = self._pw.hash_password(password)
        return await self._users.create(
            email=email.lower(), hashed_password=hashed, full_name=full_name, role=UserRole.user
        )

    async def invite(self, admin: User, email: str, role: UserRole) -> Invitation:
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may invite users.")
        if await self._users.get_by_email(email):
            raise ConflictError(f"A user with email '{email}' already exists.")
        token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRY_DAYS)
        return await self._invitations.create(
            email=email.lower(), role=role, invited_by=admin.id, token=token, expires_at=expires_at
        )

    async def accept_invitation(self, token: str, full_name: str, password: str) -> User:
        invitation = await self._invitations.get_by_token(token)
        if not invitation:
            raise NotFoundError("Invitation not found.")
        if invitation.accepted_at:
            raise ConflictError("Invitation already used.")
        if invitation.expires_at < datetime.now(timezone.utc):
            raise ValidationError("Invitation has expired.")
        self._pw.validate_password_policy(password)
        hashed = self._pw.hash_password(password)
        user = await self._users.create(
            email=invitation.email, hashed_password=hashed,
            full_name=full_name, role=invitation.role,
        )
        await self._invitations.mark_accepted(token)
        return user

    async def deactivate_user(self, admin: User, target_id: uuid.UUID) -> None:
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may deactivate users.")
        await self._users.set_active(target_id, False)

    async def list_users(self, admin: User, limit: int, offset: int) -> list[User]:
        if admin.role != UserRole.admin:
            raise ForbiddenError("Only admins may list users.")
        return list(await self._users.list_active(limit=limit, offset=offset))
```

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Unit tests pass with mocked repositories
- [ ] `register` → happy path, duplicate email, weak password — all tested
- [ ] `accept_invitation` → valid, expired, already-used — all tested
- [ ] Linter passed
