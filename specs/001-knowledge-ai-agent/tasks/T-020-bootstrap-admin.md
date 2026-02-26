# T-020 — Bootstrap First Admin (FR-024)

---
id: T-020
title: Bootstrap First Admin Account from Environment Variables (FR-024)
status: Not Started
created: 2026-02-26
phase: Phase 0 — Foundation
user_story: US3
requirements: [FR-024, FR-034]
priority: P1
depends_on: [T-018, T-021, T-022]
blocks: [T-025, T-038]
estimated_effort: 1.5h
---

## Goal

On every application startup, check if the `users` table is empty. If it is, create the first admin account using credentials sourced from environment variables (`BOOTSTRAP_ADMIN_EMAIL` + `BOOTSTRAP_ADMIN_PASSWORD`). The bootstrapped admin must have `must_change_password=True` so they are forced to set a new password on first login (FR-024).

If any users already exist, the bootstrap silently skips — it is idempotent and must never create duplicate accounts.

---

## Acceptance Criteria

- [ ] `bootstrap_admin()` is an `async` function called in the FastAPI `lifespan` startup after migrations run
- [ ] Reads `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` from `settings`; both must be non-empty strings
- [ ] If `BOOTSTRAP_ADMIN_EMAIL` or `BOOTSTRAP_ADMIN_PASSWORD` is not set, logs a warning and skips — does NOT raise an exception (allows running without bootstrap in test environments)
- [ ] Checks `SELECT COUNT(*) FROM users` — if ≥ 1, logs "Admin already exists, skipping bootstrap" and returns
- [ ] Creates a `User` with `role=UserRole.admin`, `is_active=True`, `must_change_password=True`
- [ ] Password is hashed via `PasswordService.hash_password()` and validated via `validate_password_policy()`
- [ ] If bootstrap password fails policy, logs an error and raises `ValueError` at startup (prevents silent misconfiguration)
- [ ] On success, logs `"Bootstrap admin created: {email}"` at INFO level
- [ ] Entire function is wrapped in a database transaction — rollback on any error
- [ ] Unit tests: first-run creates admin, second-run skips, missing env vars skip, weak password raises

---

## Files to Create / Update

| Path | Action |
|------|---------|
| `backend/src/core/bootstrap.py` | Create — `bootstrap_admin()` function |
| `backend/src/core/config.py` | Update — add `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` optional fields |
| `backend/src/main.py` | Update — call `bootstrap_admin()` in lifespan after migrations |
| `backend/tests/unit/test_bootstrap.py` | Create |

---

## Implementation

### `backend/src/core/config.py` additions

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Bootstrap — optional; only used on first startup
    BOOTSTRAP_ADMIN_EMAIL: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD: str | None = None
```

### `backend/src/core/bootstrap.py`

```python
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import async_session_factory
from src.core.config import settings
from src.models.user import User, UserRole
from src.services.password_service import PasswordService

logger = logging.getLogger(__name__)


async def bootstrap_admin() -> None:
    """
    Create the first admin account from environment variables.
    Idempotent — silently skips if any user already exists.

    Called once in the FastAPI lifespan startup, after Alembic migrations.
    """
    email = settings.BOOTSTRAP_ADMIN_EMAIL
    password = settings.BOOTSTRAP_ADMIN_PASSWORD

    if not email or not password:
        logger.warning(
            "BOOTSTRAP_ADMIN_EMAIL or BOOTSTRAP_ADMIN_PASSWORD not set — "
            "skipping bootstrap. Set both to create the first admin account."
        )
        return

    # Validate password policy early — fail loudly at startup, not silently
    try:
        PasswordService.validate_password_policy(password)
    except ValueError as exc:
        logger.error(
            "Bootstrap admin password does not meet policy: %s. "
            "Fix BOOTSTRAP_ADMIN_PASSWORD and restart.",
            exc,
        )
        raise

    async with async_session_factory() as session:
        async with session.begin():
            # Check if any user exists
            count_result = await session.execute(
                select(func.count()).select_from(User)
            )
            user_count = count_result.scalar_one()

            if user_count > 0:
                logger.info(
                    "Bootstrap skipped — %d user(s) already exist.", user_count
                )
                return

            # Create the bootstrap admin
            hashed = PasswordService.hash_password(password)
            admin = User(
                email=email,
                hashed_password=hashed,
                role=UserRole.admin,
                is_active=True,
                must_change_password=True,  # FR-024: forced change on first login
            )
            session.add(admin)

        logger.info("Bootstrap admin created: %s", email)
```

### Update `backend/src/main.py` lifespan

```python
from src.core.bootstrap import bootstrap_admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — ORDER IS IMPORTANT
    await run_migrations()       # T-014: schema must exist before bootstrap
    await init_redis()           # T-018: Redis ready
    await bootstrap_admin()      # T-020: create first admin if needed
    yield
    # Shutdown
    await close_redis()
    await engine.dispose()
```

---

## Tests

### `backend/tests/unit/test_bootstrap.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


async def test_bootstrap_creates_admin_when_no_users(mock_db_session):
    """First run: no users → admin is created."""
    from src.core.bootstrap import bootstrap_admin

    mock_db_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one=MagicMock(return_value=0)),  # COUNT = 0
        ]
    )
    mock_db_session.add = MagicMock()

    with (
        patch("src.core.bootstrap.settings") as mock_settings,
        patch("src.core.bootstrap.async_session_factory") as mock_factory,
    ):
        mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@test.com"
        mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "SecurePass1!"
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db_session.begin.return_value.__aenter__ = AsyncMock()
        mock_db_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        await bootstrap_admin()
        mock_db_session.add.assert_called_once()


async def test_bootstrap_skips_when_users_exist(mock_db_session):
    """Second run: users exist → skip without creating."""
    from src.core.bootstrap import bootstrap_admin

    mock_db_session.execute = AsyncMock(
        side_effect=[MagicMock(scalar_one=MagicMock(return_value=1))]
    )
    mock_db_session.add = MagicMock()

    with (
        patch("src.core.bootstrap.settings") as mock_settings,
        patch("src.core.bootstrap.async_session_factory") as mock_factory,
    ):
        mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@test.com"
        mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "SecurePass1!"
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db_session.begin.return_value.__aenter__ = AsyncMock()
        mock_db_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        await bootstrap_admin()
        mock_db_session.add.assert_not_called()


async def test_bootstrap_skips_when_env_vars_missing():
    """No env vars set → skip without error."""
    from src.core.bootstrap import bootstrap_admin
    with patch("src.core.bootstrap.settings") as mock_settings:
        mock_settings.BOOTSTRAP_ADMIN_EMAIL = None
        mock_settings.BOOTSTRAP_ADMIN_PASSWORD = None
        await bootstrap_admin()  # Should not raise


async def test_bootstrap_raises_on_weak_password():
    """Weak password → raise ValueError at startup."""
    from src.core.bootstrap import bootstrap_admin
    with patch("src.core.bootstrap.settings") as mock_settings:
        mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@test.com"
        mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "weak"
        with pytest.raises(ValueError):
            await bootstrap_admin()
```

---

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Testing | pytest + httpx + Playwright · ≥80% coverage |

### Domain Rules
- `bootstrap_admin` executes **once on startup** and only if zero users exist (FR-024) — never expose this via API
- `must_change_password=True` is NON-NEGOTIABLE for the bootstrap admin (FR-024)
- Password policy is enforced on the bootstrap password too (FR-034)
- Bootstrap env vars (`BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`) are only used for initial setup; after the admin logs in and changes their password, these env vars can be removed
- This function MUST be called AFTER `run_migrations()` — the `users` table must exist
