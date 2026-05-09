"""Shared SQL safety validator.

Replaces two divergent in-tree implementations:

* ``src.connectors.database_connector.SqlDatabaseConnector._validate_query``
  — sqlparse-based, strict, only handles PG-flavoured SQL.
* ``src.agent.nodes.text_to_query.is_safe_sql``
  — regex keyword blocklist with documented false-positives on column
  names like ``update_at`` / ``call`` / ``delete_at``.

This module enforces the same ruleset across all four PRD-listed dialects
(PostgreSQL, MySQL, MSSQL, MongoDB-via-fallback) using ``sqlglot`` — a
multi-dialect AST parser.

Rules enforced (post-parse, walking the AST):
    * exactly one statement (no semicolon-separated batches)
    * top-level statement must be a SELECT (or CTE that ends in SELECT)
    * no SET operators: UNION / INTERSECT / EXCEPT (data exfiltration vector)
    * no DML / DDL / DCL nodes anywhere in the tree
      (INSERT, UPDATE, DELETE, MERGE, DROP, CREATE, ALTER, TRUNCATE,
       GRANT, REVOKE, COPY, CALL, EXECUTE)

Public surface:
    SqlValidationResult       — frozen dataclass (immutable)
    validate_sql(sql, dialect)
    inject_limit(sql, n, dialect)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SqlValidationResult:
    """Outcome of a :func:`validate_sql` call.

    ``reason`` is human-readable text safe for admin logs — it never
    embeds the raw query string (FR-020).  ``error_key`` is a stable
    machine-readable token callers can branch on.
    """

    is_safe: bool
    reason: str | None = None
    error_key: str | None = None


# Stable error keys — callers branch on these, never on ``reason``.
ERROR_MULTIPLE_STATEMENTS: Final[str] = "multiple_statements"
ERROR_NOT_SELECT: Final[str] = "not_select"
ERROR_FORBIDDEN_SET_OPERATOR: Final[str] = "forbidden_set_operator"
ERROR_FORBIDDEN_KEYWORD: Final[str] = "forbidden_keyword"
ERROR_PARSE: Final[str] = "parse_error"


# ---------------------------------------------------------------------------
# AST node classes that MUST NOT appear anywhere in a validated tree.
# ---------------------------------------------------------------------------
# Resolved via ``getattr`` so the module imports cleanly even if a future
# sqlglot release renames or removes one of these classes.  ``exp.Command``
# is sqlglot's catch-all for unsupported / dialect-specific verbs like
# MSSQL ``EXEC sp_evil`` and Postgres ``COPY ... TO PROGRAM`` (when the
# parser doesn't have a dedicated node) — keeping it in the deny list is
# what makes that test case fail closed.
_FORBIDDEN_NODE_NAMES: Final[tuple[str, ...]] = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "AlterColumn",
    "TruncateTable",
    "Truncate",
    "Grant",
    "Revoke",
    "Copy",
    "Command",
)


def _resolve_node_classes(names: tuple[str, ...]) -> tuple[type[exp.Expression], ...]:
    """Look up sqlglot AST classes by name; skip any missing in this version."""
    resolved: list[type[exp.Expression]] = []
    seen: set[type[exp.Expression]] = set()
    for name in names:
        cls = getattr(exp, name, None)
        if isinstance(cls, type) and issubclass(cls, exp.Expression) and cls not in seen:
            resolved.append(cls)
            seen.add(cls)
    return tuple(resolved)


_FORBIDDEN_NODES: Final[tuple[type[exp.Expression], ...]] = _resolve_node_classes(
    _FORBIDDEN_NODE_NAMES
)

_FORBIDDEN_SET_OPERATORS: Final[tuple[type[exp.Expression], ...]] = _resolve_node_classes(
    ("Union", "Intersect", "Except")
)


# ---------------------------------------------------------------------------
# validate_sql
# ---------------------------------------------------------------------------


def validate_sql(sql: str, dialect: str = "postgres") -> SqlValidationResult:
    """Validate that *sql* is a single, safe, read-only SELECT statement.

    The function never raises on unsafe input — it returns a result object
    instead, so callers can log + skip without try/except scaffolding.

    Args:
        sql:     the raw SQL text to validate.
        dialect: a sqlglot dialect name.  ``"postgres"``, ``"mysql"``,
                 ``"tsql"`` (== MSSQL), or any other sqlglot-known value.
                 The dialect controls *parsing* only — the safety rules
                 themselves are dialect-independent.

    Returns:
        :class:`SqlValidationResult` with ``is_safe=True`` only when every
        rule passes.  ``reason`` is always populated when ``is_safe`` is
        ``False`` and is safe to surface to admins (no raw query text).
    """
    if not isinstance(sql, str) or not sql.strip():
        return SqlValidationResult(
            is_safe=False,
            reason="SQL is empty or not a string.",
            error_key=ERROR_PARSE,
        )

    # --- Parse -----------------------------------------------------------
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except (ParseError, TokenError) as exc:
        # sqlglot's ParseError messages can include fragments of the input
        # string — strip those before surfacing.
        return SqlValidationResult(
            is_safe=False,
            reason=f"SQL failed to parse ({type(exc).__name__}).",
            error_key=ERROR_PARSE,
        )
    except Exception:  # noqa: BLE001 — defensive: any parser bug fails closed.
        return SqlValidationResult(
            is_safe=False,
            reason="SQL failed to parse (unknown parser error).",
            error_key=ERROR_PARSE,
        )

    # sqlglot emits ``[None]`` for input that tokenises to nothing
    # (whitespace + comments only).  Treat that as a parse error.
    real_statements = [s for s in statements if s is not None]
    if not real_statements:
        return SqlValidationResult(
            is_safe=False,
            reason="SQL parsed to no statements.",
            error_key=ERROR_PARSE,
        )

    # --- Multi-statement -------------------------------------------------
    if len(real_statements) > 1:
        return SqlValidationResult(
            is_safe=False,
            reason="SQL must contain exactly one statement.",
            error_key=ERROR_MULTIPLE_STATEMENTS,
        )

    root = real_statements[0]

    # --- Top-level shape: SELECT (possibly inside a CTE) -----------------
    # ``exp.With`` wraps a SELECT/Union/Intersect/Except.  Its ``this``
    # attribute is the body — that's what we test below.
    body: exp.Expression = root.this if isinstance(root, exp.With) else root

    if _FORBIDDEN_SET_OPERATORS and isinstance(body, _FORBIDDEN_SET_OPERATORS):
        return SqlValidationResult(
            is_safe=False,
            reason=(
                "SET operators (UNION / INTERSECT / EXCEPT) are not allowed "
                "— they enable cross-table data exfiltration."
            ),
            error_key=ERROR_FORBIDDEN_SET_OPERATOR,
        )

    if not isinstance(body, exp.Select):
        return SqlValidationResult(
            is_safe=False,
            reason="Only SELECT statements are allowed.",
            error_key=ERROR_NOT_SELECT,
        )

    # --- Walk the entire tree for forbidden subtrees ---------------------
    # Catches DML hidden inside CTEs, subqueries, lateral joins, etc.
    for node in root.walk():
        if _FORBIDDEN_SET_OPERATORS and isinstance(node, _FORBIDDEN_SET_OPERATORS):
            return SqlValidationResult(
                is_safe=False,
                reason=(
                    "SET operators (UNION / INTERSECT / EXCEPT) are not allowed "
                    "— they enable cross-table data exfiltration."
                ),
                error_key=ERROR_FORBIDDEN_SET_OPERATOR,
            )
        if _FORBIDDEN_NODES and isinstance(node, _FORBIDDEN_NODES):
            kind = type(node).__name__.upper()
            return SqlValidationResult(
                is_safe=False,
                reason=f"SQL contains forbidden operation: {kind}.",
                error_key=ERROR_FORBIDDEN_KEYWORD,
            )

    return SqlValidationResult(is_safe=True)


# ---------------------------------------------------------------------------
# inject_limit
# ---------------------------------------------------------------------------


def inject_limit(sql: str, n: int = 100, dialect: str = "postgres") -> str:
    """Append ``LIMIT n`` to *sql* — or replace a larger one — via the AST.

    Replaces the old ``SELECT * FROM (<sql>) AS _q LIMIT N`` subquery wrap,
    which produced invalid SQL on MSSQL (which uses ``OFFSET / FETCH NEXT``
    instead of ``LIMIT``).

    Behaviour:
        * No existing LIMIT  → adds ``LIMIT n``.
        * Existing LIMIT > n → replaces with ``LIMIT n``.
        * Existing LIMIT ≤ n → leaves the smaller value alone.
        * MSSQL ``FETCH NEXT k ROWS ONLY`` is treated like LIMIT.

    The caller is responsible for having already passed *sql* through
    :func:`validate_sql` — this function does NOT re-validate.

    Raises:
        ValueError: if *sql* fails to parse.  Validators always run first,
        so this is purely defensive.
    """
    if n <= 0:
        raise ValueError(f"limit must be positive, got {n!r}")

    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except (ParseError, TokenError) as exc:
        raise ValueError(
            f"inject_limit: SQL failed to parse: {type(exc).__name__}"
        ) from exc

    if parsed is None:
        raise ValueError("inject_limit: SQL parsed to None.")

    # Determine the SELECT body (CTE-aware).
    body = parsed.this if isinstance(parsed, exp.With) else parsed

    if not isinstance(body, exp.Select):
        # Defensive: callers should have validated first.
        raise ValueError("inject_limit: top-level expression is not a SELECT.")

    # Read existing numeric limit (LIMIT or FETCH NEXT) — leave smaller ones alone.
    existing = _existing_numeric_limit(body)
    if existing is not None and existing <= n:
        return parsed.sql(dialect=dialect)

    # ``Select.limit(n)`` returns a *new* tree; sqlglot handles dialect rendering
    # (LIMIT vs OFFSET/FETCH NEXT) at .sql() time.
    new_body = body.limit(n)

    # If the original used MSSQL's FETCH NEXT, sqlglot may keep the stale
    # ``fetch`` arg alongside the new ``limit``.  Drop it so the renderer
    # doesn't emit BOTH "FETCH NEXT" and "LIMIT".
    if "fetch" in new_body.args and new_body.args.get("fetch") is not None:
        new_body.set("fetch", None)

    if isinstance(parsed, exp.With):
        new_root = parsed.copy()
        new_root.set("this", new_body)
        return new_root.sql(dialect=dialect)

    return new_body.sql(dialect=dialect)


def _existing_numeric_limit(select: exp.Select) -> int | None:
    """Best-effort read of the integer LIMIT / FETCH NEXT count.

    Returns ``None`` if there is no limit, or if the limit is non-literal
    (an expression we can't safely compare against ``n``).
    """
    limit_node = select.args.get("limit")
    if limit_node is not None:
        # Different sqlglot versions wrap the count differently:
        # newer versions store an ``exp.Limit`` whose ``.expression`` is
        # the count; older versions store the literal directly.
        candidate: object | None = limit_node
        for attr in ("expression", "this"):
            inner = getattr(limit_node, attr, None)
            if isinstance(inner, exp.Literal):
                candidate = inner
                break
        if isinstance(candidate, exp.Literal) and candidate.is_int:
            return int(candidate.this)

    fetch_node = select.args.get("fetch")
    if fetch_node is not None:
        for attr in ("count", "expression", "this"):
            count = getattr(fetch_node, attr, None)
            if isinstance(count, exp.Literal) and count.is_int:
                return int(count.this)

    return None
