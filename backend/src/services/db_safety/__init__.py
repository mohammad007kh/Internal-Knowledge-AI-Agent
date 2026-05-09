"""DB safety helpers: defense-in-depth read-only enforcement at the
SQLAlchemy/asyncpg layer for source-database connections.

Phase 1 covers PostgreSQL only. MySQL / SQL Server / MongoDB equivalents
will land in Phase 2.
"""
from src.services.db_safety.connection_hardening import (
    harden_postgres_connection,
    read_only_session,
)

__all__ = ["harden_postgres_connection", "read_only_session"]
