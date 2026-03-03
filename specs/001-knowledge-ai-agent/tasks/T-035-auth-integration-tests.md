# T-035 â€” Auth Integration Tests (Backend)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-035 |
| **Title** | Auth Integration Tests â€” pytest httpx suite for all auth endpoints |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Backend / Tests |
| **Depends on** | T-008, T-025, T-026, T-027, T-028, T-029 |
| **Blocks** | T-039 |
| **Est. complexity** | M |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC |
| Error Format | RFC 7807 Problem Details â€” all non-2xx API responses |
| Testing | pytest + httpx Â· â‰¥80% coverage |
| Database | PostgreSQL 16 â€” test DB separate from app DB (env var `TEST_DATABASE_URL`) |

### Domain Rules
- All passwords validated via validate_password_policy() (FR-034)
- Invitations are the only path to new accounts (FR-021)
- Every test must be isolated â€” use per-test DB transactions that roll back after the test

---

## Goal
Implement the full pytst integration test suite for Phase 1 backend auth. Use `pytest-asyncio`
with a `conftest.py` that provides an in-memory httpx `AsyncClient` against a real (test)
PostgreSQL database. Each test group exercises one endpoint family; assertions validate
JSON body shape, HTTP status, cookie presence, and RFC 7807 error format.

---

## Deliverables

### 1. `backend/tests/conftest.py`
```python
import asyncio
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import create_app
from app.core.config import settings
from app.models.base import Base
from app.core.db import get_db
from app.services.password_service import PasswordService
from app.models.user import User, UserRole

# â”€â”€ Test database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TEST_DATABASE_URL = settings.TEST_DATABASE_URL  # default: same as DATABASE_URL + "_test"

_test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_db():
    """Create all tables once per test session."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a per-test session that rolls back after each test."""
    async with _test_engine.begin() as conn:
        async with _TestSession(bind=conn) as session:
            yield session
            await conn.rollback()


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI app with the test DB session."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# â”€â”€ Helper factories â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest_asyncio.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    """Create and persist an active admin user."""
    pw_hash = PasswordService().hash("Admin@1234")
    user = User(
        email="admin@test.local",
        password_hash=pw_hash,
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture()
async def regular_user(db_session: AsyncSession) -> User:
    """Create and persist an active regular user."""
    pw_hash = PasswordService().hash("User@12345")
    user = User(
        email="user@test.local",
        password_hash=pw_hash,
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def get_access_token(client: AsyncClient, email: str, password: str) -> str:
    """Helper â€” login and return the access token string."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
```

---

### 2. `backend/tests/integration/test_auth_login.py`
```python
import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
class TestLogin:
    async def test_login_success(self, client: AsyncClient, admin_user: User):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": "Admin@1234"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 900
        assert "must_change_password" in body
        # httpOnly refresh cookie must be set
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password(self, client: AsyncClient, admin_user: User):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": "wrongpass"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["status"] == 401
        assert "type" in body   # RFC 7807 shape

    async def test_login_unknown_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@test.local", "password": "whatever"},
        )
        assert resp.status_code == 401

    async def test_login_inactive_user(self, client: AsyncClient, db_session, regular_user: User):
        regular_user.is_active = False
        await db_session.flush()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.local", "password": "User@12345"},
        )
        assert resp.status_code == 401
```

---

### 3. `backend/tests/integration/test_auth_refresh_logout.py`
```python
import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestRefreshLogout:
    async def test_refresh_success(self, client: AsyncClient, admin_user: User):
        # Login to get a refresh cookie
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": "Admin@1234"},
        )
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_refresh_no_cookie_returns_401(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    async def test_logout_clears_cookie(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@test.local", "Admin@1234")
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        # Cookie should be cleared (empty value or max-age=0)
        assert resp.cookies.get("refresh_token", "") == "" or \
               "max-age=0" in (resp.headers.get("set-cookie") or "").lower()
```

---

### 4. `backend/tests/integration/test_auth_password.py`
```python
import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestPasswordReset:
    async def test_reset_request_always_202(self, client: AsyncClient):
        """Server always returns 202 to prevent email enumeration."""
        resp = await client.post(
            "/api/v1/auth/password-reset",
            json={"email": "nobody@test.local"},
        )
        assert resp.status_code == 202

    async def test_reset_request_known_email_also_202(
        self, client: AsyncClient, regular_user: User
    ):
        resp = await client.post(
            "/api/v1/auth/password-reset",
            json={"email": "user@test.local"},
        )
        assert resp.status_code == 202

    async def test_change_password_success(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@test.local", "User@12345")
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "User@12345",
                "new_password": "NewPass@99",
            },
        )
        assert resp.status_code == 204

        # Should be able to login with new password
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.local", "password": "NewPass@99"},
        )
        assert login.status_code == 200

    async def test_change_password_wrong_current(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@test.local", "User@12345")
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "WrongCurrent",
                "new_password": "NewPass@99",
            },
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestInvitationSetup:
    async def test_setup_invalid_token(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/setup",
            json={"invitation_token": "bad_token", "password": "Valid@1234"},
        )
        assert resp.status_code == 400

    async def test_setup_weak_password(self, client: AsyncClient, db_session, admin_user):
        # Create a real invitation first
        from app.models.invitation import Invitation
        import secrets
        from datetime import datetime, timezone, timedelta
        raw = secrets.token_urlsafe(32)
        inv = Invitation(
            email="newuser@test.local",
            raw_token=raw,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(inv)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/auth/setup",
            json={"invitation_token": raw, "password": "weak"},
        )
        assert resp.status_code == 422
```

---

### 5. `backend/tests/integration/test_users_router.py`
```python
import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestUsersRouter:
    async def test_list_users_admin(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@test.local", "Admin@1234")
        resp = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    async def test_list_users_regular_user_forbidden(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@test.local", "User@12345")
        resp = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_list_users_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 401

    async def test_invite_user(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@test.local", "Admin@1234")
        resp = await client.post(
            "/api/v1/users/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "invitee@test.local", "role": "user"},
        )
        assert resp.status_code == 201

    async def test_change_role(
        self, client: AsyncClient, admin_user: User, regular_user: User
    ):
        token = await get_access_token(client, "admin@test.local", "Admin@1234")
        resp = await client.patch(
            f"/api/v1/users/{regular_user.id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_deactivate_user(
        self, client: AsyncClient, admin_user: User, regular_user: User
    ):
        token = await get_access_token(client, "admin@test.local", "Admin@1234")
        resp = await client.delete(
            f"/api/v1/users/{regular_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
```

---

## Files to Create

| Path | Description |
|---|---|
| `backend/tests/conftest.py` | Session/test-scoped fixtures: engine, session rollback, user factories |
| `backend/tests/integration/test_auth_login.py` | Login endpoint tests |
| `backend/tests/integration/test_auth_refresh_logout.py` | Refresh + logout tests |
| `backend/tests/integration/test_auth_password.py` | Password reset, change, invitation setup tests |
| `backend/tests/integration/test_users_router.py` | Users CRUD + invite tests |

---

## Gate Criteria
- `make test` passes: all tests green, no warnings
- Coverage report shows â‰¥80% on `app/api/v1/auth.py` and `app/api/v1/users.py`
- `test_login_wrong_password` confirms RFC 7807 shape (status, type, detail fields present)
- `test_reset_request_always_202` verifies non-enumeration behaviour
- Each test is isolated â€” running tests in any order produces the same result
