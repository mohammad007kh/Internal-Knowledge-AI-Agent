"""
DB-specific fixtures re-exported for convenience.
The canonical db_session and apply_migrations fixtures live in
backend/tests/conftest.py (session-scoped). This module provides
helpers for direct DB access in tests.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


@pytest.fixture
async def truncate_all(db_session: AsyncSession):
    """Explicit truncation helper for tests that need a clean slate mid-test."""
    await db_session.execute(
        text("TRUNCATE users, invitations, sources CASCADE")
    )
    await db_session.commit()
