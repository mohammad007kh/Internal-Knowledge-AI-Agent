"""Alembic async migration environment.

Reads DATABASE_URL from the environment at runtime.
Uses SQLAlchemy's AsyncEngine so migrations run against asyncpg connections.

Usage
-----
    # From backend/ directory:
    alembic upgrade head
    alembic downgrade base
    alembic revision --autogenerate -m "description"
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import src.models.chunk  # noqa: F401  — T-051
import src.models.document  # noqa: F401  — T-051
import src.models.refresh_token  # noqa: F401  — T-012
import src.models.source  # noqa: F401  — T-040
import src.models.user  # noqa: F401  — T-020
from alembic import context

# ─── Import all models here so Base.metadata is fully populated ─────────────
# Add new model imports below as tables are created.  Each import registers
# the model's Table with Base.metadata for autogenerate to detect.
#
# HOW TO ADD A NEW MODEL:
# 1. Create your model file in src/models/ inheriting from Base
# 2. Add an import line below (uncomment or add new)
# 3. Run: alembic revision --autogenerate -m "description_of_change"
# 4. Review the generated migration, then: alembic upgrade head
from src.models.base import Base  # noqa: F401

# Future model imports (uncomment as tasks are implemented):
# import src.models.invitation         # T-020 (if separate file)
# import src.models.sync_job           # T-040
# import src.models.chat_session       # T-060
# import src.models.chat_message       # T-060
# import src.models.user_source_access # T-060
# import src.models.company_policy     # T-080
# import src.models.guardrail_event    # T-080
# import src.models.llm_configuration  # T-080

# ─── Alembic Config ──────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from environment (never hardcode credentials).
_database_url: str = os.environ["DATABASE_URL"]
config.set_main_option("sqlalchemy.url", _database_url)

target_metadata = Base.metadata


# ─── Offline migrations ──────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required).

    Generates SQL that can be reviewed and applied manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ─── Online migrations (async) ───────────────────────────────────────────────
def _do_run_migrations(connection) -> None:  # type: ignore[type-arg]
    """Synchronous callback invoked inside run_sync() with an active connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using AsyncEngine."""
    connectable: AsyncEngine = create_async_engine(
        _database_url,
        echo=False,
        pool_pre_ping=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


# ─── Entry point ─────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
