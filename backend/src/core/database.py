"""Async SQLAlchemy engine factory, AsyncSession, and get_db FastAPI dependency.

Requires:
    settings.DATABASE_URL — configured in src.core.config (T-004)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import settings  # T-004 creates this module

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession and handles cleanup."""
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Celery-task session helper
# ---------------------------------------------------------------------------
# Celery tasks call ``asyncio.run(...)`` per invocation, which spins up a fresh
# event loop each time. The module-level ``engine`` above is created at import
# time and its asyncpg connections bind to whichever loop first opens them —
# so reusing it across loops produces:
#     RuntimeError: ... attached to a different loop
#     RuntimeError: Event loop is closed
#
# ``task_engine``/``task_session`` build a throwaway engine + sessionmaker
# inside the task's loop and dispose of them on exit. The module-level engine
# stays untouched and continues to serve FastAPI request-scoped traffic.


def _build_task_engine() -> AsyncEngine:
    """Create a fresh AsyncEngine sized for a single short-lived Celery task.

    pool_size is intentionally small because the engine lives only for the
    duration of one ``asyncio.run`` call.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )


@asynccontextmanager
async def task_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Yield a fresh AsyncEngine bound to the current event loop, then dispose.

    Use this when a Celery task needs to share one engine across several
    sessions or hand a session_factory to multiple services. For the simple
    "one session, one task" case prefer :func:`task_session`.
    """
    eng = _build_task_engine()
    try:
        yield eng
    finally:
        await eng.dispose()


@asynccontextmanager
async def task_session() -> AsyncGenerator[AsyncSession, None]:
    """One-shot AsyncSession for a Celery task.

    Creates a fresh engine in the current event loop, hands out a session,
    disposes of the engine on exit so no asyncpg connection survives past the
    loop. Required because Celery's ``asyncio.run`` + module-level engines
    mix poorly (see module docstring above).
    """
    eng = _build_task_engine()
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as session:
            yield session
    finally:
        await eng.dispose()
