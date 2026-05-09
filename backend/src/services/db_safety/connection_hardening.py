"""Connection-hardening helpers for Postgres source databases.

Provides defense-in-depth read-only enforcement at the SQLAlchemy/asyncpg
layer.  Even if the admin supplies a credential with write access, the
framework refuses to mutate via three independent layers:

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

The network/role layer (CREATE ROLE ... LOGIN NOINHERIT, GRANT SELECT only,
``pg_hba.conf`` restrictions) is the admin's responsibility — see commit
#131 once it lands.

Phase 1 = Postgres only.  MySQL / MSSQL / Mongo equivalents land in Phase 2.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)

import sqlalchemy as sa

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


def _is_postgres_url(connection_string: str) -> bool:
    """Return True iff *connection_string* uses a Postgres scheme."""
    scheme = urlsplit(connection_string).scheme.lower()
    return scheme in _POSTGRES_SCHEMES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def harden_postgres_connection(
    connection_string: str,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> str:
    """Augment a Postgres URL with libpq client options that force read-only
    transactions and a server-side ``statement_timeout``.

    The function is **idempotent** — calling it on an already-hardened URL
    returns the same string (only the timeout is updated if it differs).

    Parameters
    ----------
    connection_string:
        A Postgres connection URL.  Both the bare ``postgresql://`` flavour
        and the asyncpg dialect ``postgresql+asyncpg://`` are accepted.
    statement_timeout_ms:
        Server-side ``statement_timeout`` in milliseconds.  Defaults to
        :data:`DEFAULT_STATEMENT_TIMEOUT_MS` (30 s).  Must be a positive int.

    Returns
    -------
    str
        The hardened connection string with the libpq ``options`` query
        parameter set to::

            -c default_transaction_read_only=on -c statement_timeout=<N>

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


@asynccontextmanager
async def read_only_session(
    engine: "AsyncEngine",
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> AsyncIterator["AsyncSession"]:
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
