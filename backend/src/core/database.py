"""Async SQLAlchemy engine factory, AsyncSession, and get_db FastAPI dependency.

Requires:
    settings.DATABASE_URL — configured in src.core.config (T-004)
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings  # T-004 creates this module

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
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
