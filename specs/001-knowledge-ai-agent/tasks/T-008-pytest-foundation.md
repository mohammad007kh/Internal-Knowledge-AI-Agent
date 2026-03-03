---
id: T-008
title: pytest Foundation â€” conftest, Fixtures, Async Test Client, Test Database
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-003, T-004]
---

## ðŸ“‹ Embedded Context

**Stack**: Python 3.12 Â· FastAPI Â· SQLAlchemy 2.x async Â· pytest + httpx Â· asyncio_mode=auto  
**Test org**: `backend/tests/unit/` and `backend/tests/integration/`; colocated conftest files  
**Coverage gate**: â‰¥80% line coverage (enforced in CI via `--cov-fail-under=80`)  
**Pattern**: Async fixtures with `pytest-asyncio`; `anyio_backend = "asyncio"`; isolated test DB per session

---

## ðŸŽ¯ Objective

Create the pytest foundation: root `conftest.py` with async test client, isolated test database (via `alembic upgrade head` on a temp schema), override DI container for test services, and shared fixtures (admin user, regular user, auth headers).

---

## ðŸ› ï¸ Files to Create

| Path | Purpose |
|------|---------|
| `backend/tests/conftest.py` | Root conftest: async engine, session, HTTP client, container overrides |
| `backend/tests/fixtures/__init__.py` | Shared fixture package |
| `backend/tests/fixtures/auth.py` | `admin_token`, `user_token`, `admin_headers`, `user_headers` fixtures |
| `backend/tests/fixtures/db.py` | `db_session`, `apply_migrations`, `clean_tables` fixtures |
| `backend/tests/unit/conftest.py` | Unit-test-specific overrides (mock external services) |
| `backend/tests/integration/conftest.py` | Integration-test-specific fixtures (real DB, mock MinIO) |

---

## Implementation

**`backend/tests/conftest.py`:**
```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from alembic.config import Config
from alembic import command
from src.main import create_app
from src.core.config import settings
from src.core.database import get_db
from src.core.container import container

TEST_DATABASE_URL = settings.DATABASE_URL.replace("/knowledge_agent", "/test_knowledge_agent")

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def apply_migrations():
    """Run alembic upgrade head on test database."""
    engine = create_async_engine(TEST_DATABASE_URL)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    yield
    # Optional: command.downgrade(cfg, "base")
    await engine.dispose()

@pytest.fixture
async def db_session(apply_migrations):
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()

@pytest.fixture
async def client(db_session: AsyncSession):
    """HTTPX async test client with DB session override."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
async def clean_tables(db_session: AsyncSession):
    yield
    # Truncate all data tables after each test
    await db_session.execute(text("TRUNCATE users, invitations, sources CASCADE"))
    await db_session.commit()
```

**`backend/tests/fixtures/auth.py`:**
```python
import pytest
from httpx import AsyncClient
from tests.factories import UserFactory

@pytest.fixture
async def admin_user(db_session):
    return await UserFactory.create(role="admin", db=db_session)

@pytest.fixture
async def regular_user(db_session):
    return await UserFactory.create(role="user", db=db_session)

@pytest.fixture
async def admin_headers(client: AsyncClient, admin_user):
    res = await client.post("/api/v1/auth/login",
        json={"email": admin_user.email, "password": "TestPassword123"})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

**Key patterns:**
- All test fixtures are `async def` since backend is async-first
- `pytest.ini` (in pyproject.toml) sets `asyncio_mode = "auto"`
- Factories use `pytest_factoryboy` or manual async factory pattern
- Mocked services (MinIO, Celery, LLM) use `unittest.mock.AsyncMock`

---

## ðŸ”Œ Wiring Checklist

- [ ] `pyproject.toml` has `[tool.pytest.ini_options] asyncio_mode = "auto"`
- [ ] Test DB URL points to `test_knowledge_agent` database (not `knowledge_agent`)
- [ ] `apply_migrations` fixture scope is `session` (runs once per test run)
- [ ] `client` fixture overrides `get_db` with test session
- [ ] `clean_tables` autouse fixture truncates data after each test

---

## âœ… Verification

```bash
cd backend
# Run with no tests yet â€” verify conftest loads without errors
python -m pytest tests/ --collect-only 2>&1 | grep "ERROR" | wc -l
# Expected: 0 (no collection errors)

# Verify test DB migrations run
python -m pytest tests/ -k "not test_" --setup-only 2>&1 | tail -5
# Expected: "no tests ran" but no errors
```

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
