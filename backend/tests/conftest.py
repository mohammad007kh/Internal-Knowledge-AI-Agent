import asyncio
import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Integration-test guard
# ---------------------------------------------------------------------------
# The heavy app imports (pgvector, full ORM stack, Settings validation) are
# only needed when running integration tests that require a live database.
# Unit tests in tests/unit/ must be runnable without Docker / pgvector.
#
# Set RUN_INTEGRATION_TESTS=1 (or run via the integration test suite) to
# activate this conftest's database fixtures.  Without that variable, only
# the lightweight unit-test conftest.py files in subdirectories are used.
# ---------------------------------------------------------------------------

_backend_dir = Path(__file__).parent.parent  # backend/
_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

if _INTEGRATION:
    # Load .env before importing anything from src so that Settings can resolve
    # all required fields AND alembic's env.py gets DATABASE_URL in os.environ.
    load_dotenv(_backend_dir / ".env", override=True)

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.api.v1.auth import _get_auth_service  # noqa: E402
    from src.api.v1.users import _get_user_service  # noqa: E402
    from src.core.config import settings  # noqa: E402
    from src.core.database import get_db  # noqa: E402
    from src.main import create_app  # noqa: E402
    from src.models.user import User, UserRole  # noqa: E402
    from src.repositories.invitation_repository import InvitationRepository  # noqa: E402
    from src.repositories.refresh_token_repository import RefreshTokenRepository  # noqa: E402
    from src.repositories.user_repository import UserRepository  # noqa: E402
    from src.services.auth_service import AuthService  # noqa: E402
    from src.services.email_service import EmailService  # noqa: E402
    from src.services.password_service import PasswordService  # noqa: E402
    from src.services.user_service import UserService  # noqa: E402

    TEST_DATABASE_URL = settings.DATABASE_URL.replace(
        "/knowledge_agent", "/test_knowledge_agent"
    )



@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


if _INTEGRATION:

    @pytest.fixture(scope="session", autouse=True)
    def apply_migrations():
        """Run alembic upgrade head on test database (once per session).

        Uses subprocess so alembic's env.py can call asyncio.run() inside its own
        clean process — no event loop conflict. The full +asyncpg URL is passed so
        SQLAlchemy inside alembic uses the asyncpg driver (the only driver installed).

        Before running migrations, ensures that the test_knowledge_agent database
        exists, creating it if necessary (connects to the postgres maintenance DB).
        """
        import asyncpg  # asyncpg is the installed async driver

        async def _ensure_test_db() -> None:
            # Connect to the postgres maintenance DB on the same host/port.
            # Always DROP + RECREATE so migrations run against a clean slate,
            # preventing "already exists" errors from half-migrated test runs.
            conn = await asyncpg.connect(
                host="localhost",
                port=5434,
                user="postgres",
                password="postgres",
                database="postgres",
            )
            try:
                # Terminate any open connections to the test DB before dropping
                await conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = 'test_knowledge_agent'"
                )
                # DROP DATABASE cannot run inside a transaction
                await conn.execute(
                    "DROP DATABASE IF EXISTS test_knowledge_agent"
                )
                await conn.execute("CREATE DATABASE test_knowledge_agent")
            finally:
                await conn.close()

        asyncio.run(_ensure_test_db())

        venv_python = str(_backend_dir.parent / ".venv" / "Scripts" / "python.exe")
        env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
        result = subprocess.run(
            [venv_python, "-m", "alembic", "upgrade", "head"],
            cwd=str(_backend_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Alembic upgrade failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        yield

    @pytest.fixture
    async def db_session(apply_migrations) -> AsyncSession:  # type: ignore[misc]
        """Provide a fresh AsyncSession per test."""
        engine = create_async_engine(TEST_DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
        await engine.dispose()

    @pytest.fixture
    async def client(db_session: AsyncSession) -> AsyncClient:  # type: ignore[misc]
        """HTTPX async test client.

        Overrides the DI-container factory functions for auth_service and
        user_service so that all repository operations run inside the test
        db_session (connected to test_knowledge_agent on port 5434).
        Using dependency_overrides[get_db] alone is insufficient because the
        route dependencies call Container.auth_service() / Container.user_service()
        directly, bypassing FastAPI's get_db dependency entirely.
        """
        app = create_app()

        def _make_user_svc() -> UserService:
            return UserService(
                user_repo=UserRepository(session=db_session),
                invitation_repo=InvitationRepository(session=db_session),
                password_service=PasswordService(),
                refresh_token_repo=RefreshTokenRepository(session=db_session),
                email_service=EmailService(),
            )

        def _make_auth_svc() -> AuthService:
            return AuthService(
                user_repo=UserRepository(session=db_session),
                refresh_repo=RefreshTokenRepository(session=db_session),
                user_service=_make_user_svc(),
                password_service=PasswordService(),
            )

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[_get_auth_service] = _make_auth_svc
        app.dependency_overrides[_get_user_service] = _make_user_svc
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.fixture(autouse=True)
    async def clean_tables():
        """Truncate all data tables before each test for isolation.

        Uses its own dedicated connection (not the test db_session) so the
        TRUNCATE is committed and visible to every fixture that runs afterwards,
        regardless of which session they use.  Runs in the setup phase (before
        yield) so admin_user / regular_user always start with an empty table.

        Table names match the actual migration DDL:
          - user_refresh_tokens  (migration 0002)
          - invitations          (migration 0003)
          - password_reset_tokens (migration 0004)
          - users                (migration 0003)
          - source_permissions   (migration 0005 / T-043)
          - sources              (migration 0005 / T-043)
          - chat_messages        (T-078)
          - chat_sessions        (T-078)
          - system_health_events (T-095 / FR-033)
        """
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE chat_messages, chat_sessions,"
                    " source_permissions, sources, users,"
                    " user_refresh_tokens, invitations,"
                    " password_reset_tokens, system_health_events"
                    " RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()
        yield

    # ---------------------------------------------------------------------------
    # Shared helper
    # ---------------------------------------------------------------------------

    async def get_access_token(client: AsyncClient, email: str, password: str) -> str:
        """Login and return the access_token string."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ---------------------------------------------------------------------------
    # User fixtures
    # ---------------------------------------------------------------------------

    @pytest_asyncio.fixture()
    async def admin_user(db_session: AsyncSession) -> User:  # type: ignore[misc]
        """An active admin user seeded in the test DB."""
        pw_hash = PasswordService.hash_password("Admin@1234")
        user = User(
            email="admin@example.com",
            full_name="Admin User",
            hashed_password=pw_hash,
            role=UserRole.admin,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    @pytest_asyncio.fixture()
    async def regular_user(db_session: AsyncSession) -> User:  # type: ignore[misc]
        """An active regular user seeded in the test DB."""
        pw_hash = PasswordService.hash_password("User@12345")
        user = User(
            email="user@example.com",
            full_name="Regular User",
            hashed_password=pw_hash,
            role=UserRole.user,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        return user
