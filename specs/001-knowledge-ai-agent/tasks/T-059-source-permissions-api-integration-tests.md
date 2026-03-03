# T-059 Â· Source Permissions API Integration Tests + Phase 2 Sign-Off

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
PostgreSQL 16 + pgvector Â· UUID PKs Â· soft-delete + audit columns
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user)
Fernet (connection configs at rest)
RFC 7807 Problem Details â€” all non-2xx API responses
pytest + httpx + Playwright Â· â‰¥80% coverage
Docker Compose 9 services
```

## Goal
HTTP API-level integration tests for source-permission endpoints using HTTPX async test client
against a real FastAPI app + PostgreSQL. Completes Phase 2 (Sources & Connectors) and closes
the T-052â€“T-059 bucket.

---

## File 1 â€” `tests/integration/test_source_permissions_api.py`

```python
"""
Integration tests â€” Source Permissions API
Routes under test:
  POST   /api/v1/sources/{source_id}/permissions
  DELETE /api/v1/sources/{source_id}/permissions/{user_id}
  GET    /api/v1/sources/{source_id}/permissions
  GET    /api/v1/users/me/sources

All tests use real DB (db_session fixture) and real JWT tokens.
No external services are hit (ConnectorFactory mocked).
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient

from app.models.enums import SourceType, UserRole
from app.models.source import Source
from app.models.user import User
from app.models.source_permission import SourcePermission
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(admin_user.id), role=UserRole.ADMIN.value
    )
    return {"Authorization": f"Bearer {token}"}


def _user_headers(regular_user: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(regular_user.id), role=UserRole.USER.value
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_source(db_session, owner_id: uuid.UUID, name: str = "test-src") -> Source:
    src = Source(
        name=name,
        source_type=SourceType.WEB_URL,
        config_encrypted=b"placeholder",
        owner_id=owner_id,
        is_active=True,
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    return src


async def _make_user(db_session, email_prefix: str = "u") -> User:
    from app.core.security import hash_password

    user = User(
        email=f"{email_prefix}-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password1"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_admin(db_session) -> User:
    from app.core.security import hash_password

    admin = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password1"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


# ---------------------------------------------------------------------------
# Tests â€” POST /sources/{id}/permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grant_permission_admin_201(
    async_client: AsyncClient, db_session
) -> None:
    """Admin can grant a user access to a source â†’ 201 Created."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    src = await _make_source(db_session, owner_id=admin.id)

    resp = await async_client.post(
        f"/api/v1/sources/{src.id}/permissions",
        json={"user_id": str(user.id)},
        headers=_admin_headers(admin),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["source_id"] == str(src.id)
    assert body["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_grant_permission_duplicate_409(
    async_client: AsyncClient, db_session
) -> None:
    """Granting the same permission twice â†’ 409 Conflict (RFC 7807)."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    src = await _make_source(db_session, owner_id=admin.id)

    payload = {"user_id": str(user.id)}
    hdrs = _admin_headers(admin)

    # First grant
    r1 = await async_client.post(
        f"/api/v1/sources/{src.id}/permissions", json=payload, headers=hdrs
    )
    assert r1.status_code == 201

    # Duplicate grant
    r2 = await async_client.post(
        f"/api/v1/sources/{src.id}/permissions", json=payload, headers=hdrs
    )
    assert r2.status_code == 409
    body = r2.json()
    # RFC 7807 Problem Details
    assert body["type"] is not None
    assert body["status"] == 409


@pytest.mark.asyncio
async def test_grant_permission_non_admin_403(
    async_client: AsyncClient, db_session
) -> None:
    """Non-admin user attempting to grant permissions â†’ 403 Forbidden."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    other = await _make_user(db_session, email_prefix="other")
    src = await _make_source(db_session, owner_id=admin.id)

    resp = await async_client.post(
        f"/api/v1/sources/{src.id}/permissions",
        json={"user_id": str(other.id)},
        headers=_user_headers(user),
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_grant_permission_missing_source_404(
    async_client: AsyncClient, db_session
) -> None:
    """Granting permission on a non-existent source â†’ 404 (RFC 7807)."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    fake_id = uuid.uuid4()

    resp = await async_client.post(
        f"/api/v1/sources/{fake_id}/permissions",
        json={"user_id": str(user.id)},
        headers=_admin_headers(admin),
    )

    assert resp.status_code == 404
    assert resp.json()["status"] == 404


# ---------------------------------------------------------------------------
# Tests â€” DELETE /sources/{id}/permissions/{user_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_permission_admin_204(
    async_client: AsyncClient, db_session
) -> None:
    """Admin revokes an existing permission â†’ 204 No Content."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    src = await _make_source(db_session, owner_id=admin.id)

    # Grant first
    g = await async_client.post(
        f"/api/v1/sources/{src.id}/permissions",
        json={"user_id": str(user.id)},
        headers=_admin_headers(admin),
    )
    assert g.status_code == 201

    # Revoke
    resp = await async_client.delete(
        f"/api/v1/sources/{src.id}/permissions/{user.id}",
        headers=_admin_headers(admin),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_revoke_nonexistent_permission_404(
    async_client: AsyncClient, db_session
) -> None:
    """Revoking a permission that was never granted â†’ 404 (RFC 7807)."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    src = await _make_source(db_session, owner_id=admin.id)

    resp = await async_client.delete(
        f"/api/v1/sources/{src.id}/permissions/{user.id}",
        headers=_admin_headers(admin),
    )

    assert resp.status_code == 404
    assert resp.json()["status"] == 404


# ---------------------------------------------------------------------------
# Tests â€” GET /sources/{id}/permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_permissions_admin_200(
    async_client: AsyncClient, db_session
) -> None:
    """Admin can list all user_ids that have access to a source."""
    admin = await _make_admin(db_session)
    u1 = await _make_user(db_session, email_prefix="ua")
    u2 = await _make_user(db_session, email_prefix="ub")
    src = await _make_source(db_session, owner_id=admin.id)
    hdrs = _admin_headers(admin)

    await async_client.post(
        f"/api/v1/sources/{src.id}/permissions",
        json={"user_id": str(u1.id)},
        headers=hdrs,
    )
    await async_client.post(
        f"/api/v1/sources/{src.id}/permissions",
        json={"user_id": str(u2.id)},
        headers=hdrs,
    )

    resp = await async_client.get(
        f"/api/v1/sources/{src.id}/permissions", headers=hdrs
    )
    assert resp.status_code == 200
    body = resp.json()
    assert str(u1.id) in body["user_ids"]
    assert str(u2.id) in body["user_ids"]


# ---------------------------------------------------------------------------
# Tests â€” GET /users/me/sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_sources_returns_permitted_source_ids(
    async_client: AsyncClient, db_session
) -> None:
    """Regular user receives only the source IDs they have been granted."""
    admin = await _make_admin(db_session)
    user = await _make_user(db_session)
    src_a = await _make_source(db_session, owner_id=admin.id, name="src-a")
    src_b = await _make_source(db_session, owner_id=admin.id, name="src-b")
    hdrs_admin = _admin_headers(admin)

    # Grant access to src_a only
    await async_client.post(
        f"/api/v1/sources/{src_a.id}/permissions",
        json={"user_id": str(user.id)},
        headers=hdrs_admin,
    )

    resp = await async_client.get(
        "/api/v1/users/me/sources", headers=_user_headers(user)
    )
    assert resp.status_code == 200
    ids = resp.json()  # list[str]
    assert str(src_a.id) in ids
    assert str(src_b.id) not in ids


@pytest.mark.asyncio
async def test_me_sources_admin_sees_all(
    async_client: AsyncClient, db_session
) -> None:
    """Admin calling /users/me/sources sees ALL active source IDs (RBAC bypass)."""
    admin = await _make_admin(db_session)
    src_a = await _make_source(db_session, owner_id=admin.id, name="admin-src-a")
    src_b = await _make_source(db_session, owner_id=admin.id, name="admin-src-b")

    resp = await async_client.get(
        "/api/v1/users/me/sources", headers=_admin_headers(admin)
    )
    assert resp.status_code == 200
    ids = resp.json()
    assert str(src_a.id) in ids
    assert str(src_b.id) in ids


# ---------------------------------------------------------------------------
# FR-019 enforcement â€” no config_encrypted in responses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_response_never_exposes_config(
    async_client: AsyncClient, db_session
) -> None:
    """
    FR-019/FR-020: Source GET response must NOT contain 'config_encrypted'.
    Even if admin fetches their own source.
    """
    admin = await _make_admin(db_session)
    src = await _make_source(db_session, owner_id=admin.id)

    resp = await async_client.get(
        f"/api/v1/sources/{src.id}", headers=_admin_headers(admin)
    )
    assert resp.status_code == 200
    body_text = resp.text
    assert "config_encrypted" not in body_text
    # Also must not contain raw bytes representation
    assert "b'placeholder'" not in body_text
```

---

## File 2 â€” Phase 2 Sign-Off Checklist (append to task file)

### Phase 2 Acceptance Criteria â€” T-052 through T-059

| FR | Description | Verified by |
|---|---|---|
| FR-019 | Source data never returned to users without permission | `test_me_sources_returns_permitted_source_ids` + `test_source_response_never_exposes_config` |
| FR-020 | `config_encrypted` / connection strings never appear in API responses | `test_source_response_never_exposes_config` + T-057 FR-020 log tests |
| FR-024 | `bootstrap_admin` runs at startup if zero users exist | T-039 sign-off (Phase 1 closure) |
| FR-033 | Celery Beat runs with exactly 1 replica | Docker Compose `deploy.replicas: 1` (T-014); validated T-065 |
| FR-034 | Password policy enforced (8+, upper, lower, digit) | T-036 unit + T-039 API tests |
| FR-035 | File upload size capped (default 50 MB from `app_config.yaml`) | T-047 connector test `test_size_limit_rejected` |

---

## Acceptance Criteria

- [ ] `test_grant_permission_admin_201` â€” POST returns 201 + correct `source_id`/`user_id`
- [ ] `test_grant_permission_duplicate_409` â€” second POST returns RFC 7807 409 body
- [ ] `test_grant_permission_non_admin_403` â€” regular user cannot grant â†’ 403
- [ ] `test_grant_permission_missing_source_404` â€” non-existent source â†’ RFC 7807 404
- [ ] `test_revoke_permission_admin_204` â€” DELETE after grant â†’ 204
- [ ] `test_revoke_nonexistent_permission_404` â€” DELETE with no prior grant â†’ RFC 7807 404
- [ ] `test_list_permissions_admin_200` â€” GET returns both user UUIDs
- [ ] `test_me_sources_returns_permitted_source_ids` â€” user sees only permitted sources
- [ ] `test_me_sources_admin_sees_all` â€” admin bypasses permission filter (FR-019 RBAC)
- [ ] `test_source_response_never_exposes_config` â€” `config_encrypted` absent from JSON (FR-020)
- [ ] All 10 tests pass with `asyncio_mode=auto`; no `sync_to_async` wrappers needed
- [ ] Phase 2 sign-off table complete â€” FR-019, FR-020, FR-033, FR-034, FR-035 all mapped
