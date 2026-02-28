import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> dict:
    """Create an admin user directly in the DB and return its data."""
    password_hash = bcrypt.hashpw(b"TestPassword123!", bcrypt.gensalt()).decode()
    result = await db_session.execute(
        text(
            "INSERT INTO users (email, hashed_password, role, is_active) "
            "VALUES (:email, :hashed_password, :role, :is_active) "
            "RETURNING id, email, role"
        ),
        {
            "email": "admin@test.com",
            "hashed_password": password_hash,
            "role": "admin",
            "is_active": True,
        },
    )
    await db_session.commit()
    row = result.fetchone()
    return {"id": row.id, "email": row.email, "role": row.role,
            "password": "TestPassword123!"}


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> dict:
    """Create a regular user directly in the DB and return its data."""
    password_hash = bcrypt.hashpw(b"TestPassword123!", bcrypt.gensalt()).decode()
    result = await db_session.execute(
        text(
            "INSERT INTO users (email, hashed_password, role, is_active) "
            "VALUES (:email, :hashed_password, :role, :is_active) "
            "RETURNING id, email, role"
        ),
        {
            "email": "user@test.com",
            "hashed_password": password_hash,
            "role": "user",
            "is_active": True,
        },
    )
    await db_session.commit()
    row = result.fetchone()
    return {"id": row.id, "email": row.email, "role": row.role,
            "password": "TestPassword123!"}


@pytest.fixture
async def admin_headers(client: AsyncClient, admin_user: dict) -> dict:
    """Return Authorization headers for the admin user."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_user["email"], "password": admin_user["password"]},
    )
    token = res.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def user_headers(client: AsyncClient, regular_user: dict) -> dict:
    """Return Authorization headers for the regular user."""
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": regular_user["email"], "password": regular_user["password"]},
    )
    token = res.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}
