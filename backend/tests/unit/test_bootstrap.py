"""Unit tests for ``src.core.bootstrap.bootstrap_admin`` (T-020 / FR-024)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.bootstrap import bootstrap_admin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_settings(
    email: str | None = "admin@example.com",
    password: str | None = "Admin1234!",
) -> MagicMock:
    """Return a mock ``settings`` object with bootstrap credentials."""
    s = MagicMock()
    s.BOOTSTRAP_ADMIN_EMAIL = email
    s.BOOTSTRAP_ADMIN_PASSWORD = password
    return s


def _mock_session(user_count: int = 0) -> AsyncMock:
    """Return an ``AsyncMock`` that behaves like an async SQLAlchemy session.

    ``session.execute(...)`` returns a result whose ``scalar_one()`` returns
    *user_count*.
    """
    session = AsyncMock()

    # result.scalar_one() -> user_count
    result = MagicMock()
    result.scalar_one.return_value = user_count
    session.execute.return_value = result

    # ``session.begin()`` is a *synchronous* call that returns an async
    # context manager (mirrors real SQLAlchemy ``AsyncSession.begin()``).
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    return session


def _mock_session_factory(session: AsyncMock) -> MagicMock:
    """Return a callable that, when used as ``async with factory() as s``,
    yields *session*.
    """
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("src.core.bootstrap.async_session_factory")
@patch("src.core.bootstrap.settings")
async def test_bootstrap_creates_admin_when_no_users(
    mock_settings: MagicMock,
    mock_factory: MagicMock,
) -> None:
    """First run: table is empty → admin row must be inserted."""
    mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
    mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "Admin1234!"

    session = _mock_session(user_count=0)
    real_factory = _mock_session_factory(session)
    mock_factory.return_value = real_factory.return_value

    await bootstrap_admin()

    session.add.assert_called_once()
    added_user = session.add.call_args[0][0]
    assert added_user.email == "admin@example.com"
    assert added_user.is_active is True
    assert added_user.must_change_password is True


@pytest.mark.asyncio
@patch("src.core.bootstrap.async_session_factory")
@patch("src.core.bootstrap.settings")
async def test_bootstrap_skips_when_users_exist(
    mock_settings: MagicMock,
    mock_factory: MagicMock,
) -> None:
    """Second run: users already present → nothing created."""
    mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
    mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "Admin1234!"

    session = _mock_session(user_count=1)
    real_factory = _mock_session_factory(session)
    mock_factory.return_value = real_factory.return_value

    await bootstrap_admin()

    session.add.assert_not_called()


@pytest.mark.asyncio
@patch("src.core.bootstrap.async_session_factory")
@patch("src.core.bootstrap.settings")
async def test_bootstrap_skips_when_env_vars_missing(
    mock_settings: MagicMock,
    mock_factory: MagicMock,
) -> None:
    """If credentials are ``None``, bootstrap must skip without error."""
    mock_settings.BOOTSTRAP_ADMIN_EMAIL = None
    mock_settings.BOOTSTRAP_ADMIN_PASSWORD = None

    await bootstrap_admin()

    # Factory should never be called — we exit early.
    mock_factory.assert_not_called()


@pytest.mark.asyncio
@patch("src.core.bootstrap.settings")
async def test_bootstrap_raises_on_weak_password(
    mock_settings: MagicMock,
) -> None:
    """A password that violates policy must raise ``ValueError`` at startup."""
    mock_settings.BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
    mock_settings.BOOTSTRAP_ADMIN_PASSWORD = "weak"

    with pytest.raises(ValueError, match="Password must be at least 8 characters"):
        await bootstrap_admin()
