import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from alembic.config import Config
from alembic import command
from src.main import create_app
from src.core.config import settings
from src.core.database import get_db

TEST_DATABASE_URL = settings.DATABASE_URL.replace(
    "/knowledge_agent", "/test_knowledge_agent"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session", autouse=True)
async def apply_migrations():
    """Run alembic upgrade head on test database (once per session)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("+asyncpg", ""))
    command.upgrade(cfg, "head")
    yield
    await engine.dispose()


@pytest.fixture
async def db_session(apply_migrations) -> AsyncSession:
    """Provide a fresh AsyncSession per test."""
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    """HTTPX async test client with DB session override."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def clean_tables(db_session: AsyncSession):
    """Truncate all data tables after each test for isolation."""
    yield
    try:
        await db_session.execute(
            text("TRUNCATE users, invitations, sources CASCADE")
        )
        await db_session.commit()
    except Exception:
        await db_session.rollback()
