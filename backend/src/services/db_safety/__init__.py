"""DB safety helpers: defense-in-depth read-only enforcement at the
SQLAlchemy/asyncpg layer for source-database connections.

Two coordinated layers:

- :mod:`sql_validator` — sqlglot-AST-based statement validator that admits
  only single SELECT statements and rejects DML/DDL/DCL/multi-statement/
  set-operator inputs. Shared by the connector's read-only execution path
  and the text-to-query agent node so both enforce identical rules.

- :mod:`connection_hardening` — Postgres-only (Phase 1) connection-string
  augmentation + transaction-scoped read_only_session context manager.
  MySQL / SQL Server / MongoDB equivalents will land in Phase 2.
"""

from src.services.db_safety.connection_hardening import (
    harden_postgres_connection,
    read_only_session,
)
from src.services.db_safety.sql_validator import (
    SqlValidationResult,
    inject_limit,
    validate_sql,
)

__all__ = [
    "SqlValidationResult",
    "harden_postgres_connection",
    "inject_limit",
    "read_only_session",
    "validate_sql",
]
