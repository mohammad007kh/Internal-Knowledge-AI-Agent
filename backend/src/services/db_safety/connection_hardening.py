"""Connection-hardening helpers for source databases (Postgres / MySQL / MSSQL).

Provides defense-in-depth read-only enforcement at the SQLAlchemy/driver
layer.  Even if the admin supplies a credential with write access, the
framework refuses to mutate via several independent layers:

PostgreSQL
----------
1. **libpq client options** — :func:`harden_postgres_connection` augments
   the connection URL with ``-c default_transaction_read_only=on`` and
   ``-c statement_timeout=N``.  Every transaction starts read-only and
   has a server-side timeout, regardless of role privileges.
2. **Per-transaction SET LOCAL** — :func:`read_only_session` issues
   ``SET LOCAL transaction_read_only TO on`` and
   ``SET LOCAL statement_timeout = N`` at the start of every transaction.
   ``LOCAL`` scopes the setting to the transaction so connection-pool
   reuse cannot leak state.
3. **Explicit ROLLBACK on exit** — even SELECTs that took advisory locks
   or advanced sequences are rolled back on context-manager exit (success
   or failure path).

MySQL / MariaDB
---------------
:func:`harden_mysql_connection` registers an ``"connect"`` event handler
on the engine that, on **every** pooled connection, issues:

* ``SET SESSION TRANSACTION READ ONLY`` — the session refuses DML/DDL.
* ``SET SESSION max_execution_time = <ms>`` (MySQL 5.7.8+) AND
  ``SET SESSION max_statement_time = <secs>`` (MariaDB) — a server-side
  per-statement timeout.  We set both defensively; the flavour that
  doesn't recognise one just raises, which we swallow.
* ``SET SESSION innodb_lock_wait_timeout = <secs>`` — bounds how long a
  row-lock wait blocks (introspection should never block on a writer).

Each ``SET`` is wrapped in a try/except that logs at WARNING and continues
— a managed-MySQL flavour (PlanetScale, Aurora, ...) may reject one.

SQL Server (MSSQL)  ⚠️  IMPORTANT — limited read-only enforcement
-----------------------------------------------------------------
SQL Server has **no clean per-session read-only switch** like Postgres's
``default_transaction_read_only`` GUC.  Genuine read-only on SQL Server
requires *either*:

* an ``ApplicationIntent=ReadOnly`` connection routed to an AlwaysOn
  *readable secondary replica* (not generally available), *or*
* a least-privilege login — ``GRANT SELECT`` only, with ``DENY INSERT,
  UPDATE, DELETE, ...`` everything else.

So for MSSQL the *enforcement* of read-only is the **sqlglot SELECT-only
gate** (:func:`src.services.db_safety.validate_sql`) on the sampling
SELECT, plus the fact that SQLAlchemy reflection is read-only by nature.
:func:`harden_mssql_connection` only does what it *can* per-session:

* ``SET LOCK_TIMEOUT <ms>`` — caps how long a lock wait blocks.
* ``SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED`` — so introspection
  does not take shared locks / block writers.  **This is NOT read-only
  enforcement** — it's lock-avoidance only.
* the command/query timeout is set on the engine (``connect_args``
  ``timeout=`` — honoured by pyodbc/aioodbc) by the caller.

Operators connecting an MSSQL source **should** use a SELECT-only login.

The network/role layer (CREATE ROLE ... LOGIN NOINHERIT, GRANT SELECT
only, ``pg_hba.conf`` restrictions) is the admin's responsibility.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)

import sqlalchemy as sa
from sqlalchemy import event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: URL schemes recognised as PostgreSQL.  ``postgres://`` is a deprecated
#: alias kept by libpq for backward compat.
_POSTGRES_SCHEMES = frozenset(
    {
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg",
        "postgresql+psycopg2",
        "postgres",
    }
)

#: Default server-side statement_timeout in milliseconds.  Caller can override.
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000

# Sentinel substrings used for idempotency detection.  We avoid full parsing
# because the libpq ``options`` field is space-delimited and the values are
# fixed shape (``-c key=value``).
_FLAG_READ_ONLY = "-c default_transaction_read_only=on"

#: Contract dialect literals this module knows how to harden.
HardenableDialect = Literal["postgresql", "mysql", "mssql"]

#: Sentinel attribute set on an engine once an engine-level ``connect`` handler
#: has been wired by this module.  Re-registering the handler on the same engine
#: would stack duplicates (every ``SET SESSION ...`` then runs twice), so the
#: harden_* helpers below check this first and return early if it's already
#: ``True``.  The check uses an identity comparison (``is True``) rather than
#: truthiness so a stand-in object that auto-creates attributes (a ``MagicMock``
#: in tests, say) doesn't accidentally look already-hardened on the first call.
_HARDENED_SENTINEL = "_kb_hardened"


def _already_hardened(engine: object) -> bool:
    """Return True iff *engine* has already had a ``connect`` handler wired."""
    return getattr(engine, _HARDENED_SENTINEL, None) is True


def _mark_hardened(engine: object) -> None:
    """Stamp *engine* as hardened.  No-op if the object forbids the attribute."""
    try:
        setattr(engine, _HARDENED_SENTINEL, True)
    except AttributeError:  # pragma: no cover - engine forbids attribute set
        pass


def _is_postgres_url(connection_string: str) -> bool:
    """Return True iff *connection_string* uses a Postgres scheme."""
    scheme = urlsplit(connection_string).scheme.lower()
    return scheme in _POSTGRES_SCHEMES


def _ms_to_secs_ceil(ms: int) -> int:
    """Convert *ms* to a whole number of seconds, rounding up, min 1."""
    return max(1, -(-ms // 1000))


# ---------------------------------------------------------------------------
# Public API — PostgreSQL
# ---------------------------------------------------------------------------


def postgres_asyncpg_connect_args(
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> dict[str, dict[str, str]]:
    """Return SQLAlchemy ``connect_args`` that harden an asyncpg connection.

    Prefer :func:`harden_postgres_engine_kwargs` for engine construction; it
    pairs the two outputs atomically.

    The libpq ``?options=-c key=value`` URL trick does NOT work with asyncpg
    — asyncpg's ``connect()`` rejects the ``options=`` kwarg outright. The
    correct asyncpg analogue is ``server_settings={...}``, which asyncpg
    forwards to PostgreSQL as a startup-message parameter set, giving the
    same effect: every transaction on this connection starts with
    ``default_transaction_read_only=on`` and a server-side
    ``statement_timeout``.

    Callers building an asyncpg engine should pass::

        create_async_engine(
            url,
            connect_args=postgres_asyncpg_connect_args(),
            ...
        )

    Parameters
    ----------
    statement_timeout_ms:
        Server-side ``statement_timeout`` in milliseconds.  Defaults to
        :data:`DEFAULT_STATEMENT_TIMEOUT_MS` (30 s).  Must be a positive int.

    Raises
    ------
    ValueError
        If *statement_timeout_ms* is non-positive.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )
    return {
        "server_settings": {
            "default_transaction_read_only": "on",
            "statement_timeout": str(statement_timeout_ms),
        }
    }


def _is_asyncpg_url(connection_string: str) -> bool:
    """Return True iff *connection_string* uses the asyncpg dialect."""
    return urlsplit(connection_string).scheme == "postgresql+asyncpg"


async def harden_postgres_connection(
    connection_string: str,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> str:
    """Augment a Postgres URL with libpq client options that force read-only
    transactions and a server-side ``statement_timeout``.

    Prefer :func:`harden_postgres_engine_kwargs` for engine construction; it
    pairs the two outputs atomically.

    The function is **idempotent** — calling it on an already-hardened URL
    returns the same string (only the timeout is updated if it differs).

    .. note::
       For asyncpg URLs (``postgresql+asyncpg://``) this function returns
       the URL **unchanged**: asyncpg does not understand libpq's
       ``?options=`` parameter and raises
       ``TypeError: connect() got an unexpected keyword argument 'options'``
       when SQLAlchemy forwards it.  Callers must instead pass
       :func:`postgres_asyncpg_connect_args` as ``connect_args=`` to
       ``create_async_engine`` to get the equivalent
       ``server_settings={'default_transaction_read_only': 'on', ...}``
       hardening on the asyncpg side.

    Parameters
    ----------
    connection_string:
        A Postgres connection URL.  Both the bare ``postgresql://`` flavour
        and the asyncpg dialect ``postgresql+asyncpg://`` are accepted (the
        asyncpg flavour is returned unchanged — see note above).
    statement_timeout_ms:
        Server-side ``statement_timeout`` in milliseconds.  Defaults to
        :data:`DEFAULT_STATEMENT_TIMEOUT_MS` (30 s).  Must be a positive int.

    Returns
    -------
    str
        The hardened connection string with the libpq ``options`` query
        parameter set to::

            -c default_transaction_read_only=on -c statement_timeout=<N>

        OR — for ``postgresql+asyncpg://`` URLs — the original URL
        unchanged (hardening flows via ``connect_args`` instead; see note).

    Raises
    ------
    ValueError
        If *connection_string* is not a Postgres URL or
        *statement_timeout_ms* is non-positive.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )

    if not _is_postgres_url(connection_string):
        raise ValueError(
            "harden_postgres_connection only supports PostgreSQL URLs "
            f"(scheme must be one of {sorted(_POSTGRES_SCHEMES)}); got "
            f"scheme={urlsplit(connection_string).scheme!r}"
        )

    # asyncpg refuses the libpq `options=` kwarg — return the URL unchanged
    # and let the caller wire `connect_args=postgres_asyncpg_connect_args()`
    # at engine-build time.
    if _is_asyncpg_url(connection_string):
        return connection_string

    parts = urlsplit(connection_string)
    # parse_qsl with keep_blank_values=True preserves empty values; we want
    # ordered + duplicate-tolerant parsing.
    query_pairs: list[tuple[str, str]] = parse_qsl(
        parts.query, keep_blank_values=True
    )

    timeout_flag = f"-c statement_timeout={statement_timeout_ms}"
    desired_options = f"{_FLAG_READ_ONLY} {timeout_flag}"

    # Look for an existing options= entry and merge.  If multiple options=
    # entries exist (unlikely but possible), the first one wins and the rest
    # are dropped — libpq itself only honours one.
    new_query_pairs: list[tuple[str, str]] = []
    options_seen = False
    for key, value in query_pairs:
        if key == "options" and not options_seen:
            options_seen = True
            existing = unquote(value).strip()
            merged = _merge_options(existing, statement_timeout_ms)
            new_query_pairs.append(("options", merged))
        elif key == "options":
            # Drop duplicate options= entries — libpq honours only one.
            continue
        else:
            new_query_pairs.append((key, value))

    if not options_seen:
        new_query_pairs.append(("options", desired_options))

    # quote_via=quote ensures spaces become %20 (not +), which libpq parses
    # correctly.  The leading hyphen in `-c` is a sub-delim per RFC 3986
    # and never gets percent-encoded.
    new_query = urlencode(new_query_pairs, quote_via=quote)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )


# ---------------------------------------------------------------------------
# Public API — combined Postgres engine hardening (atomic pairing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PostgresEngineHardening:
    """Paired args to build a hardened Postgres async engine — produced atomically
    so a caller cannot obtain the URL without the matching connect_args.

    Security: ``url`` carries DB credentials, so it is excluded from the
    auto-generated ``repr`` (``field(repr=False)``) — the object must never leak
    the password into logs, exception frames, or Langfuse traces.
    """
    url: str = field(repr=False)
    connect_args: dict[str, Any] = field(default_factory=dict)
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS

    def as_create_async_engine_kwargs(self) -> dict[str, Any]:
        # deepcopy so a caller mutating the returned (nested) connect_args can
        # never reach into this frozen instance's shared server_settings dict.
        return {"url": self.url, "connect_args": copy.deepcopy(self.connect_args)}


async def harden_postgres_engine_kwargs(
    connection_string: str,
    *,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> PostgresEngineHardening:
    """Return the complete, paired hardening for a Postgres async engine.

    Postgres-only (rejects non-Postgres URLs, like harden_postgres_connection).
    For asyncpg: url unchanged + server_settings connect_args. For libpq drivers:
    options=-injected url + empty connect_args. Composes the two existing
    functions — does NOT reimplement the merge logic.

    Raises
    ------
    ValueError
        If *connection_string* is not a Postgres URL or
        *statement_timeout_ms* is non-positive.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )
    if not _is_postgres_url(connection_string):
        raise ValueError(
            "harden_postgres_engine_kwargs only supports PostgreSQL URLs "
            f"(scheme must be one of {sorted(_POSTGRES_SCHEMES)}); got "
            f"scheme={urlsplit(connection_string).scheme!r}"
        )

    url = await harden_postgres_connection(
        connection_string, statement_timeout_ms=statement_timeout_ms
    )
    connect_args: dict[str, Any] = (
        postgres_asyncpg_connect_args(statement_timeout_ms)
        if _is_asyncpg_url(connection_string)
        else {}
    )
    return PostgresEngineHardening(
        url=url,
        connect_args=connect_args,
        statement_timeout_ms=statement_timeout_ms,
    )


# ---------------------------------------------------------------------------
# Public API — engine-level hardening (MySQL / MSSQL) + dispatcher
# ---------------------------------------------------------------------------


def _exec_set(connection: object, statement: str) -> None:
    """Run a single ``SET ...`` on a raw DBAPI connection; swallow failures.

    A managed-MySQL flavour (Aurora, PlanetScale, ...) or an older MariaDB
    may reject a particular ``SET`` knob — we log at WARNING and continue so
    one rejected knob doesn't abort the whole connection.
    """
    cursor = None
    try:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute(statement)
    except Exception:  # noqa: BLE001 - best-effort hardening, never fatal
        logger.warning(
            "connection_hardening: server rejected %r — continuing without it",
            statement,
        )
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass


def harden_mysql_connection(
    engine: AsyncEngine,
    *,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> None:
    """Register a ``connect`` handler that hardens every pooled MySQL/MariaDB
    connection to read-only with server-side timeouts.

    On each new DBAPI connection the handler issues (each independently,
    swallowing rejections):

    * ``SET SESSION TRANSACTION READ ONLY``
    * ``SET SESSION max_execution_time = <ms>``  (MySQL 5.7.8+)
    * ``SET SESSION max_statement_time = <secs>``  (MariaDB equivalent)
    * ``SET SESSION innodb_lock_wait_timeout = <secs>``

    Parameters
    ----------
    engine:
        The async engine whose underlying ``sync_engine`` we attach the
        ``connect`` event to.  Idempotent per engine — a second call on the
        same engine is a no-op (guarded by the :data:`_HARDENED_SENTINEL`
        attribute) so duplicate ``SET SESSION ...`` handlers can't stack.
    statement_timeout_ms:
        Per-statement server-side timeout in milliseconds.  Must be positive.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )
    if _already_hardened(engine):
        return
    _mark_hardened(engine)

    timeout_secs = _ms_to_secs_ceil(statement_timeout_ms)
    statements = (
        "SET SESSION TRANSACTION READ ONLY",
        f"SET SESSION max_execution_time = {statement_timeout_ms}",
        f"SET SESSION max_statement_time = {timeout_secs}",
        f"SET SESSION innodb_lock_wait_timeout = {timeout_secs}",
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: object, _connection_record: object) -> None:
        for stmt in statements:
            _exec_set(dbapi_connection, stmt)


def harden_mssql_connection(
    engine: AsyncEngine,
    *,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> None:
    """Register a ``connect`` handler that applies the *limited* per-session
    hardening SQL Server supports.

    ⚠️  SQL Server has **no per-session read-only switch**.  Read-only is
    enforced by the sqlglot SELECT-only gate + read-only-by-nature
    reflection — operators connecting an MSSQL source should use a
    SELECT-only login.  This function only does lock-avoidance:

    * ``SET LOCK_TIMEOUT <ms>`` — caps how long a lock wait blocks.
    * ``SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED`` — introspection
      does not take shared locks / block writers (NOT read-only enforcement).

    The command/query timeout itself belongs in the engine's ``connect_args``
    (``timeout=<secs>`` — honoured by pyodbc/aioodbc); the caller sets it.

    Parameters
    ----------
    engine:
        The async engine to attach the ``connect`` event to.  Idempotent per
        engine — a second call is a no-op (guarded by the
        :data:`_HARDENED_SENTINEL` attribute).
    statement_timeout_ms:
        Used for ``SET LOCK_TIMEOUT`` (milliseconds).  Must be positive.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )
    if _already_hardened(engine):
        return
    _mark_hardened(engine)

    statements = (
        f"SET LOCK_TIMEOUT {statement_timeout_ms}",
        "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: object, _connection_record: object) -> None:
        for stmt in statements:
            _exec_set(dbapi_connection, stmt)


def mssql_connect_args(statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS) -> dict[str, int]:
    """Return ``connect_args`` that set the driver command timeout for MSSQL.

    pyodbc / aioodbc honour ``timeout`` (in *seconds*) as the command
    timeout.  Pass the result through to ``create_async_engine(...,
    connect_args=...)`` for an ``mssql+...`` URL.
    """
    return {"timeout": _ms_to_secs_ceil(statement_timeout_ms)}


def harden_connection(
    engine: AsyncEngine,
    *,
    dialect: HardenableDialect,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> None:
    """Apply the appropriate engine-level hardening for *dialect*.

    Dispatches to :func:`harden_mysql_connection` or
    :func:`harden_mssql_connection`.  For ``"postgresql"`` this is a no-op —
    Postgres hardening lives in the connection *string* (see
    :func:`harden_postgres_connection`), applied before the engine is built.

    Parameters
    ----------
    engine:
        The freshly-created async engine.
    dialect:
        ``"postgresql"`` | ``"mysql"`` | ``"mssql"``.
    statement_timeout_ms:
        Server-side per-statement timeout budget in milliseconds.
    """
    if dialect == "mysql":
        harden_mysql_connection(engine, statement_timeout_ms=statement_timeout_ms)
    elif dialect == "mssql":
        harden_mssql_connection(engine, statement_timeout_ms=statement_timeout_ms)
    elif dialect == "postgresql":
        # No-op: Postgres is hardened via the connection string.
        return
    else:  # pragma: no cover - exhaustive over the Literal
        raise ValueError(f"harden_connection: unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# Public API — Postgres read-only session
# ---------------------------------------------------------------------------


@asynccontextmanager
async def read_only_session(
    engine: AsyncEngine,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy ``AsyncSession`` bound to a read-only transaction.

    On entry the transaction issues:

    * ``SET LOCAL transaction_read_only TO on``
    * ``SET LOCAL statement_timeout = <N>``

    The ``LOCAL`` keyword scopes the setting to the current transaction so
    the underlying connection can be safely returned to the pool with no
    state leak.

    On exit (either success or exception), the transaction is **rolled
    back explicitly** — even SELECTs may have taken advisory locks or
    advanced sequences via ``nextval()``, so commit-vs-rollback is not a
    no-op for read-only workloads.

    Parameters
    ----------
    engine:
        A SQLAlchemy :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.  The
        engine itself does not need to have been hardened — calling
        :func:`harden_postgres_connection` on the URL is recommended but
        independent.
    statement_timeout_ms:
        Per-transaction ``statement_timeout`` in milliseconds.  Defaults
        to :data:`DEFAULT_STATEMENT_TIMEOUT_MS`.  Must be a positive int.
    """
    if statement_timeout_ms <= 0:
        raise ValueError(
            f"statement_timeout_ms must be positive; got {statement_timeout_ms!r}"
        )

    # Local import to avoid eager dependency on sqlalchemy.ext.asyncio at
    # module import time (e.g. for environments that only need
    # `harden_postgres_connection`).
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    session = AsyncSession(engine, expire_on_commit=False)
    try:
        async with session.begin():
            await session.execute(
                sa.text("SET LOCAL transaction_read_only TO on")
            )
            # Bind parameters cannot be used with SET LOCAL — the value must
            # be a literal.  We've already validated it is a positive int,
            # so f-string interpolation is safe here.
            await session.execute(
                sa.text(f"SET LOCAL statement_timeout = {statement_timeout_ms}")
            )
            try:
                yield session
            finally:
                # Defense in depth: explicit ROLLBACK regardless of how the
                # `with` block exits.  `session.begin()` would otherwise
                # COMMIT on success — we want ROLLBACK either way so that
                # advisory locks / sequence advances are reverted.
                await session.rollback()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _merge_options(existing: str, statement_timeout_ms: int) -> str:
    """Merge our two flags into a libpq ``options=`` value.

    Idempotent — if the read-only flag is already present and the timeout
    matches, returns *existing* unchanged.  If a different timeout is
    present we replace it with the requested one.  Any other ``-c k=v``
    entries the caller supplied are preserved.
    """
    # Tokenise on whitespace.  libpq separates -c key=value pairs with a
    # space; backslash-escapes are theoretically allowed but rare in
    # connection-string payloads, so we keep parsing simple.
    tokens = existing.split() if existing else []

    merged: list[str] = []
    saw_read_only = False
    saw_timeout = False
    timeout_str = f"-c statement_timeout={statement_timeout_ms}"

    i = 0
    while i < len(tokens):
        token = tokens[i]
        # `-c` is a separate token from its key=value payload.
        if token == "-c" and i + 1 < len(tokens):
            payload = tokens[i + 1]
            i += 2
            if payload == "default_transaction_read_only=on":
                if not saw_read_only:
                    merged.extend(["-c", payload])
                    saw_read_only = True
            elif payload.startswith("statement_timeout="):
                if not saw_timeout:
                    merged.extend(["-c", f"statement_timeout={statement_timeout_ms}"])
                    saw_timeout = True
            else:
                merged.extend(["-c", payload])
        else:
            merged.append(token)
            i += 1

    if not saw_read_only:
        merged.extend(["-c", "default_transaction_read_only=on"])
    if not saw_timeout:
        merged.extend(["-c", f"statement_timeout={statement_timeout_ms}"])

    _ = timeout_str  # kept above for grep-ability; merged via tokenisation
    return " ".join(merged)
