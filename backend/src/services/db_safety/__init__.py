"""DB safety helpers: defense-in-depth read-only enforcement at the
SQLAlchemy/driver layer for source-database connections.

Two coordinated layers:

- :mod:`sql_validator` — sqlglot-AST-based statement validator that admits
  only single SELECT statements and rejects DML/DDL/DCL/multi-statement/
  set-operator inputs. Shared by the connector's read-only execution path
  and the text-to-query agent node so both enforce identical rules.

- :mod:`connection_hardening` — per-dialect connection hardening:
  * PostgreSQL — connection-string augmentation
    (:func:`harden_postgres_connection`) + transaction-scoped
    :func:`read_only_session`.
  * MySQL / MariaDB — :func:`harden_mysql_connection` (``SET SESSION
    TRANSACTION READ ONLY`` + server-side timeouts via a ``connect`` event).
  * SQL Server — :func:`harden_mssql_connection` (``SET LOCK_TIMEOUT`` +
    ``READ UNCOMMITTED`` isolation; **no per-session read-only switch** —
    relies on the SELECT-only gate + read-only reflection).
  :func:`harden_connection` dispatches by dialect.
"""

from src.services.db_safety.connection_hardening import (
    PostgresEngineHardening,
    harden_connection,
    harden_mssql_connection,
    harden_mysql_connection,
    harden_postgres_connection,
    harden_postgres_engine_kwargs,
    mssql_connect_args,
    postgres_asyncpg_connect_args,
    read_only_session,
)
from src.services.db_safety.sql_validator import (
    SqlValidationResult,
    inject_limit,
    validate_sql,
)

__all__ = [
    "PostgresEngineHardening",
    "SqlValidationResult",
    "harden_connection",
    "harden_mssql_connection",
    "harden_mysql_connection",
    "harden_postgres_connection",
    "harden_postgres_engine_kwargs",
    "inject_limit",
    "mssql_connect_args",
    "postgres_asyncpg_connect_args",
    "read_only_session",
    "validate_sql",
]
