# T-025 â€” Auth Service

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-025 |
| **Title** | Auth Service |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Backend / Auth |
| **Depends on** | T-012, T-013, T-022, T-023 |
| **Blocks** | T-026, T-030, T-037 |
| **Est. complexity** | L |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS |
| State | React Context Â· TanStack Query Â· react-hook-form Â· Zod |
| Database | PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis Â· Beat replicas=1 STRICT |
| File Storage | MinIO Â· presigned PUT pattern |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user) |
| Encryption | Fernet (connection configs at rest) |
| AI Pipeline | LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming |
| Tracing | Langfuse self-hosted Â· every pipeline run must emit a trace |
| Error Format | RFC 7807 Problem Details â€” all non-2xx API responses |
| Logging | Structured Â· INFO level Â· X-Request-ID correlation |
| Security | CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP |
| UI | Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts |
| Naming | snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants |
| Commits | Conventional commits Â· branch pattern: NNN-description |
| Testing | pytest + httpx + Playwright Â· â‰¥80% coverage |
| Infrastructure | Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Connection strings and file paths MUST NEVER appear in user-facing output, API responses, or AI content (FR-020)
- Celery Beat MUST run with exactly 1 replica â€” duplicate-schedule prevention is critical
- File size limit is defined in `app_config.yaml`; default 50 MB â€” NOT in .env, NOT hardcoded (FR-035)
- `bootstrap_admin` executes once on startup only if zero users exist (FR-024)
- Auto-restart is capped at 3 consecutive attempts with increasing wait; stop and alert admins on failure (FR-033)
- All passwords validated via `validate_password_policy()` â€” min 8 chars, â‰¥1 uppercase, â‰¥1 lowercase, â‰¥1 number (FR-034)
- Invitations are the only path to new accounts â€” no self-registration endpoint exists (FR-021)
- Every LangGraph pipeline run MUST emit a Langfuse trace with spans per node

---

## Goal
Implement `AuthService` in `app/services/auth_service.py` â€” the single orchestrator for all authentication flows: login, token refresh, logout, invitation acceptance, password-reset request/confirm, and forced/voluntary password change.

---

## Background
JWT tokens are issued by `T-012`. Password operations live in `T-022`. User and invitation retrieval lives in `T-023`. `AuthService` coordinates these three, plus it manages the `UserRefreshToken` lifecycle to enable rotating refresh tokens and revocation.

---

## Deliverables

### 1. `app/services/auth_service.py`
```python
from datetime import datetime, timezone, timedelta
import secrets
from uuid import UUID

from app.core.errors import (
    UnauthorizedError, ForbiddenError, NotFoundError, ConflictError
)
from app.core.jwt import (
    create_access_token, create_refresh_token,
    verify_access_token, verify_refresh_token,
)
from app.models.user import User, UserRefreshToken
from app.repositories.user_repository import UserRepository, RefreshTokenRepository
from app.schemas.auth import TokenResponse
from app.services.password_service import PasswordService
from app.services.user_service import UserService


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        refresh_repo: RefreshTokenRepository,
        user_service: UserService,
        password_service: PasswordService,
    ) -> None:
        self._user_repo = user_repo
        self._refresh_repo = refresh_repo
        self._user_service = user_service
        self._password_svc = password_service

    # ------------------------------------------------------------------ #
    # Login                                                                 #
    # ------------------------------------------------------------------ #
    async def login(self, email: str, password: str) -> tuple[str, str, bool]:
        """
        Authenticate email + password.

        Returns (access_token, refresh_token_raw, must_change_password).
        Raises UnauthorizedError on bad credentials.
        Raises ForbiddenError for deactivated users.
        """
        user = await self._user_repo.get_by_email(email)
        if not user or not self._password_svc.verify_password(
            password, user.hashed_password
        ):
            raise UnauthorizedError("Invalid credentials")

        if not user.is_active:
            raise ForbiddenError("Account is deactivated")

        return await self._issue_tokens(user)

    # ------------------------------------------------------------------ #
    # Token refresh                                                          #
    # ------------------------------------------------------------------ #
    async def refresh(self, raw_token: str) -> tuple[str, str, bool]:
        """
        Rotate refresh token.

        Validates the raw token hash stored in UserRefreshToken.
        Invalidates the old record and issues new pair.
        Raises UnauthorizedError if token unknown/expired/revoked.
        """
        record = await self._refresh_repo.get_valid_by_token(raw_token)
        if not record:
            raise UnauthorizedError("Refresh token invalid or expired")

        user = await self._user_repo.get(record.user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or deactivated")

        await self._refresh_repo.revoke(record.id)
        return await self._issue_tokens(user)

    # ------------------------------------------------------------------ #
    # Logout                                                                #
    # ------------------------------------------------------------------ #
    async def logout(self, raw_token: str) -> None:
        """Revoke the supplied refresh token. No-op if already revoked."""
        record = await self._refresh_repo.get_valid_by_token(raw_token)
        if record:
            await self._refresh_repo.revoke(record.id)

    # ------------------------------------------------------------------ #
    # Accept invitation / setup account                                     #
    # ------------------------------------------------------------------ #
    async def accept_invitation(
        self, invitation_token: str, password: str
    ) -> tuple[str, str, bool]:
        """
        Accept an invitation: set password, activate user, return tokens.

        Raises NotFoundError for unknown/expired tokens.
        Raises ConflictError if already accepted.
        Raises ValueError from password policy validation.
        """
        self._password_svc.validate_password_policy(password)
        user = await self._user_service.accept_invitation(
            invitation_token, password
        )
        return await self._issue_tokens(user)

    # ------------------------------------------------------------------ #
    # Password reset â€” request                                              #
    # ------------------------------------------------------------------ #
    async def request_password_reset(self, email: str) -> str | None:
        """
        Generate a single-use password reset token (TTL 1 h).

        Returns the raw token when user exists, None otherwise.
        NEVER surfaces which case occurred to the caller (always 202 at route).
        Token is stored hashed in PasswordResetToken table.
        """
        user = await self._user_repo.get_by_email(email)
        if not user or not user.is_active:
            return None

        raw_token = secrets.token_urlsafe(32)
        await self._refresh_repo.create_password_reset_token(
            user_id=user.id,
            raw_token=raw_token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        return raw_token

    # ------------------------------------------------------------------ #
    # Password reset â€” confirm                                              #
    # ------------------------------------------------------------------ #
    async def confirm_password_reset(
        self, raw_token: str, new_password: str
    ) -> None:
        """
        Consume reset token and set new password.

        Raises UnauthorizedError for unknown/expired tokens.
        Raises ValueError from password policy validation.
        Revokes ALL active refresh tokens for the user (force re-login).
        """
        self._password_svc.validate_password_policy(new_password)
        record = await self._refresh_repo.get_valid_reset_token(raw_token)
        if not record:
            raise UnauthorizedError("Reset token invalid or expired")

        user = await self._user_repo.get(record.user_id)
        if not user:
            raise NotFoundError("User not found")

        hashed = self._password_svc.hash_password(new_password)
        await self._user_repo.update(
            user.id, {"hashed_password": hashed, "must_change_password": False}
        )
        await self._refresh_repo.consume_reset_token(record.id)
        await self._refresh_repo.revoke_all_for_user(user.id)

    # ------------------------------------------------------------------ #
    # Change password (authenticated, voluntary or forced)                  #
    # ------------------------------------------------------------------ #
    async def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """
        Verify current password, set new one, clear must_change_password.

        Raises UnauthorizedError if current_password is wrong.
        Raises ValueError from password policy validation.
        Revokes ALL existing refresh tokens (force fresh login after change).
        """
        self._password_svc.validate_password_policy(new_password)
        user = await self._user_repo.get(user_id)
        if not user:
            raise NotFoundError("User not found")

        if not self._password_svc.verify_password(
            current_password, user.hashed_password
        ):
            raise UnauthorizedError("Current password is incorrect")

        hashed = self._password_svc.hash_password(new_password)
        await self._user_repo.update(
            user.id, {"hashed_password": hashed, "must_change_password": False}
        )
        await self._refresh_repo.revoke_all_for_user(user.id)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #
    async def _issue_tokens(
        self, user: User
    ) -> tuple[str, str, bool]:
        access = create_access_token(
            subject=str(user.id), extra={"role": user.role}
        )
        raw_refresh = secrets.token_urlsafe(32)
        await self._refresh_repo.create_refresh_token(
            user_id=user.id, raw_token=raw_refresh
        )
        return access, raw_refresh, user.must_change_password
```

---

### 2. `app/repositories/refresh_token_repository.py`
Extend existing user repository module OR create a sibling file:

```python
import hashlib
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.user import UserRefreshToken, PasswordResetToken


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_valid_by_token(
        self, raw_token: str
    ) -> UserRefreshToken | None:
        token_hash = _hash_token(raw_token)
        result = await self._db.execute(
            select(UserRefreshToken).where(
                UserRefreshToken.token_hash == token_hash,
                UserRefreshToken.revoked_at.is_(None),
                UserRefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def create_refresh_token(
        self, user_id: UUID, raw_token: str
    ) -> UserRefreshToken:
        record = UserRefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self._db.add(record)
        await self._db.commit()
        await self._db.refresh(record)
        return record

    async def revoke(self, token_id: UUID) -> None:
        await self._db.execute(
            update(UserRefreshToken)
            .where(UserRefreshToken.id == token_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self._db.commit()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self._db.execute(
            update(UserRefreshToken)
            .where(
                UserRefreshToken.user_id == user_id,
                UserRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self._db.commit()

    # ---- Password reset tokens ---------------------------------------- #

    async def create_password_reset_token(
        self, user_id: UUID, raw_token: str, expires_at: datetime
    ) -> None:
        # Invalidate any existing active reset token for this user first
        await self._db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(timezone.utc))
        )
        record = PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
        self._db.add(record)
        await self._db.commit()

    async def get_valid_reset_token(
        self, raw_token: str
    ) -> PasswordResetToken | None:
        token_hash = _hash_token(raw_token)
        result = await self._db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def consume_reset_token(self, token_id: UUID) -> None:
        await self._db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(used_at=datetime.now(timezone.utc))
        )
        await self._db.commit()
```

---

### 3. `PasswordResetToken` ORM model â€” extend `app/models/user.py`
```python
class PasswordResetToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    user: Mapped["User"] = relationship(back_populates="reset_tokens")
```

Add `reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(...)` to `User`.

---

### 4. Alembic migration `0004_password_reset_tokens.py`
```
alembic revision --autogenerate -m "add_password_reset_tokens"
```
Creates `password_reset_tokens` table with index on `user_id`, unique on `token_hash`.

---

### 5. DI container wiring
In `app/containers.py`, register:
- `refresh_token_repo` â€” `RefreshTokenRepository` (session-scoped)
- `auth_service` â€” `AuthService` (session-scoped, injected with all 4 deps)

---

## Acceptance Criteria
- [ ] `login()` returns 3-tuple; raises `UnauthorizedError` for wrong creds; raises `ForbiddenError` for inactive user
- [ ] `refresh()` rotates token (old record `revoked_at` set); raises `UnauthorizedError` for expired/unknown tokens
- [ ] `logout()` revokes record; no error if already revoked
- [ ] `accept_invitation()` delegates to `UserService.accept_invitation()`, then issues tokens
- [ ] `request_password_reset()` returns `None` for unknown/inactive email (never raises)
- [ ] `confirm_password_reset()` consumes token, updates password, revokes all refresh tokens
- [ ] `change_password()` verifies current password before updating; revokes all refresh tokens
- [ ] Token hashing uses `hashlib.sha256` â€” raw token NEVER stored in DB
- [ ] `PasswordResetToken` table created via Alembic migration `0004`
- [ ] All methods are `async`; no sync DB calls
- [ ] DI container registers `RefreshTokenRepository` and `AuthService`
- [ ] Unit tests cover all 7 public methods with mocked repos

---

## FR References
| FR | Requirement |
|---|---|
| FR-021 | Invitations are the only path to new accounts |
| FR-023 | Password reset via time-limited link (1 h) |
| FR-024 | Bootstrap admin: `must_change_password=True`, cleared after change |
| FR-034 | Password policy enforced on every password-setting operation |

---

## Notes
- Tokens are NEVER stored raw â€” always SHA-256 hashed before persistence. Raw value is only in memory / cookie.
- `confirm_password_reset` revokes all refresh tokens to force re-login after a reset â€” security requirement.
- `change_password` identity: same revoking behavior applies when user chooses to change password.
- `request_password_reset` always returns 202 at the HTTP layer regardless of whether email exists (T-026 responsibility).
