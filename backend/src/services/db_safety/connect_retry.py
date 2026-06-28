"""DB connection-failure classification, retry, and admin-explanation core.

This is the *pure, offline-testable* heart of the "retry-then-officially-fail
with a clear admin explanation" feature. It deliberately knows nothing about
connectors, Celery, SQLAlchemy, or the ORM — every external dependency
(``acquire`` / ``sleep`` / ``now`` / ``jitter`` / ``classify``) is injected so
the whole module can be unit-tested without a database or an event loop clock.

Three responsibilities
-----------------------
1. **Classify** a raw driver exception into a *closed* :class:`DBConnFailureCategory`.
   Classification reads the raw exception (which may embed credentials) purely
   in memory and returns only the enum label — the raw text is NEVER persisted,
   logged, or re-raised from here (callers must sever the exception chain).
2. **Retry** a connect handshake under a :class:`RetryPolicy`: full-jitter
   backoff bounded by a wall-clock deadline, with **fail-fast on permanent
   categories** (auth / permission / db-not-found / TLS) — retrying those just
   delays an identical failure and can trip account lockout. The attempt count
   is reported honestly (a fail-fast auth error says "1 attempt", not "3").
3. **Explain** a failure to the admin via an *allowlist* of constant per-category
   sentences. Only the :data:`DBConnFailureCategory.UNKNOWN` bucket falls through
   to free text, and that text is redacted, truncated, and run past a leak
   tripwire that fails safe to a constant — so a gap in the denylist redactor
   cannot leak a DSN.

Security note: the seam re-raises :class:`DBConnectionFailed` with ``from None``
so the raw driver exception (and any DSN on its ``__cause__``) never rides the
exception chain into a traceback formatter, Langfuse trace, or log record.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, TypeVar

from src.services.db_safety.dsn_redaction import redact_dsn

__all__ = [
    "DBConnFailureCategory",
    "PERMANENT_CATEGORIES",
    "is_permanent",
    "classify",
    "RetryPolicy",
    "BACKGROUND_POLICY",
    "INTERACTIVE_POLICY",
    "TEST_CONNECTION_POLICY",
    "DBConnectionFailed",
    "connect_with_retry",
    "AdminMessage",
    "render_admin_message",
    "safe_technical_detail",
]

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Closed failure taxonomy
# ---------------------------------------------------------------------------


class DBConnFailureCategory(StrEnum):
    """Closed set of DB connect-failure categories.

    ``str``-valued so it serialises straight onto the wire / into a column as a
    stable uppercase token. The set is intentionally small and closed: a driver
    error we cannot bucket becomes :data:`UNKNOWN` (and emits telemetry), never
    a free-form string.
    """

    DB_UNREACHABLE = "DB_UNREACHABLE"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    SERVER_UNAVAILABLE = "SERVER_UNAVAILABLE"
    SERVER_OVERLOADED = "SERVER_OVERLOADED"
    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DATABASE_NOT_FOUND = "DATABASE_NOT_FOUND"
    TLS_FAILED = "TLS_FAILED"
    UNKNOWN = "UNKNOWN"


#: Deterministic failures: the input (credentials / db-name / cert) does not
#: change between attempt 1 and attempt N, so retrying cannot help and (for
#: auth) risks account lockout. The seam fails these fast at 1 attempt.
PERMANENT_CATEGORIES: Final[frozenset[DBConnFailureCategory]] = frozenset(
    {
        DBConnFailureCategory.AUTH_FAILED,
        DBConnFailureCategory.PERMISSION_DENIED,
        DBConnFailureCategory.DATABASE_NOT_FOUND,
        DBConnFailureCategory.TLS_FAILED,
    }
)


def is_permanent(category: DBConnFailureCategory) -> bool:
    """Return True if *category* is deterministic (no point retrying)."""
    return category in PERMANENT_CATEGORIES


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
#
# Driver-agnostic + dependency-free: we branch on the lowercased exception type
# name + message text rather than importing asyncpg / pyodbc / aiomysql / pymongo
# exception classes (which may not be installed in every environment, and would
# add import cost / coupling). Order matters — the *specific permanent* signals
# are checked before the *generic transient* ones, because a single driver
# message can contain both "connection" and "password authentication failed".

_TLS_SIGNALS: Final[tuple[str, ...]] = (
    "ssl",
    "tls",
    "certificate",
    "cert verify",
    "sslv3",
    "handshake failure",
    "wrong version number",
)
_AUTH_SIGNALS: Final[tuple[str, ...]] = (
    "password authentication failed",
    "authentication failed",
    "invalidpassword",
    "invalid password",
    "auth failed",
    "authentication error",
    "login failed",  # mssql
    "access denied for user",  # mysql 1045
    "authentication failure",
    "bad credentials",
    "authenticationfailed",  # mongo
)
_PERMISSION_SIGNALS: Final[tuple[str, ...]] = (
    "permission denied",
    "insufficient priv",
    "insufficientprivilege",
    "must be owner",
    "not authorized",  # mongo
    "access to the database",
)
_DB_NOT_FOUND_SIGNALS: Final[tuple[str, ...]] = (
    "does not exist",  # postgres: database "x" does not exist
    "invalidcatalogname",
    "unknown database",  # mysql
    "cannot open database",  # mssql
    "database not found",
    "no such database",
)
_OVERLOADED_SIGNALS: Final[tuple[str, ...]] = (
    "too many connections",
    "remaining connection slots",
    "max_connections",
    "connection limit",
    "sorry, too many clients",
)
_UNAVAILABLE_SIGNALS: Final[tuple[str, ...]] = (
    "starting up",
    "the database system is starting up",
    "shutting down",
    "cannotconnectnow",
    "in recovery",
    "server closed the connection",
    "connection reset",
    "broken pipe",
)
_TIMEOUT_SIGNALS: Final[tuple[str, ...]] = (
    "timeout",
    "timed out",
)
_UNREACHABLE_SIGNALS: Final[tuple[str, ...]] = (
    "connection refused",
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "no route to host",
    "network is unreachable",
    "could not translate host name",
    "could not connect to server",
    "name does not resolve",
)


def _haystack(exc: BaseException) -> str:
    """Lowercased ``<ExcType>: <message>`` for substring matching.

    The raw text may contain a DSN; this string is used ONLY for in-memory
    branching and must never be persisted, logged, or returned.
    """
    return f"{type(exc).__name__}: {exc}".lower()


def _matches(haystack: str, signals: tuple[str, ...]) -> bool:
    return any(sig in haystack for sig in signals)


def classify(exc: BaseException) -> DBConnFailureCategory:
    """Bucket a raw driver/connection exception into a closed category.

    Reads the raw exception in memory only and returns the enum label. Permanent
    (specific) signals are tested before transient (generic) ones. Anything that
    matches nothing is :data:`DBConnFailureCategory.UNKNOWN`.
    """
    hay = _haystack(exc)

    # --- permanent / specific first ---------------------------------------
    if _matches(hay, _TLS_SIGNALS):
        return DBConnFailureCategory.TLS_FAILED
    if _matches(hay, _AUTH_SIGNALS):
        return DBConnFailureCategory.AUTH_FAILED
    # A missing ROLE is an identity/auth problem, not a missing database —
    # guard it before the (deliberately broad) "does not exist" db-not-found
    # tier so `FATAL: role "x" does not exist` doesn't fail-fast as a permanent
    # DATABASE_NOT_FOUND with the wrong admin guidance.
    if "does not exist" in hay and 'role "' in hay:
        return DBConnFailureCategory.AUTH_FAILED
    if _matches(hay, _PERMISSION_SIGNALS):
        return DBConnFailureCategory.PERMISSION_DENIED
    if _matches(hay, _DB_NOT_FOUND_SIGNALS):
        return DBConnFailureCategory.DATABASE_NOT_FOUND

    # --- transient / generic ----------------------------------------------
    if _matches(hay, _OVERLOADED_SIGNALS):
        return DBConnFailureCategory.SERVER_OVERLOADED
    if _matches(hay, _UNAVAILABLE_SIGNALS):
        return DBConnFailureCategory.SERVER_UNAVAILABLE
    # Timeout: prefer the type for asyncio.TimeoutError / TimeoutError, which
    # may carry an empty message.
    if isinstance(exc, TimeoutError) or _matches(hay, _TIMEOUT_SIGNALS):
        return DBConnFailureCategory.CONNECT_TIMEOUT
    if isinstance(exc, (ConnectionRefusedError, OSError)) or _matches(
        hay, _UNREACHABLE_SIGNALS
    ):
        # NB: OSError covers socket.gaierror (DNS) — DNS failures are treated as
        # transient (DB_UNREACHABLE) for v1; rcode-splitting is a v2 refinement.
        return DBConnFailureCategory.DB_UNREACHABLE

    return DBConnFailureCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to retry a connect, with what backoff and deadline.

    ``transient_attempts`` is the cap for *transient* categories. Permanent
    categories always resolve to 1 attempt unless explicitly overridden in
    ``overrides`` — so "three times" is the honoured default for blips while a
    rejected password fails fast. The per-category ``overrides`` map keeps the
    decision data-driven: the owner can flip any category's budget without a
    code change.
    """

    name: str
    transient_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 4.0
    deadline: float = 20.0
    overrides: Mapping[DBConnFailureCategory, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Defensive-copy + freeze so a caller that keeps a reference to the
        # passed dict can't mutate this "frozen" policy after construction.
        object.__setattr__(
            self, "overrides", MappingProxyType(dict(self.overrides))
        )

    def max_attempts_for(self, category: DBConnFailureCategory) -> int:
        """Resolve the attempt budget for *category* under this policy."""
        if category in self.overrides:
            return max(1, self.overrides[category])
        if is_permanent(category):
            return 1
        return max(1, self.transient_attempts)


#: Background jobs (schema study, sync ingestion): honour "three times" with
#: full-jitter backoff under a ~20s wall-clock deadline.
BACKGROUND_POLICY: Final[RetryPolicy] = RetryPolicy(
    name="background",
    transient_attempts=3,
    base_delay=1.0,
    max_delay=4.0,
    deadline=20.0,
)

#: Interactive chat (text-to-query): latency-sensitive — exactly one quick retry
#: to paper over a sub-second blip, hard ~3s cap; permanent still fails fast.
INTERACTIVE_POLICY: Final[RetryPolicy] = RetryPolicy(
    name="interactive",
    transient_attempts=2,
    base_delay=0.2,
    max_delay=1.0,
    deadline=3.0,
)

#: Admin "test connection": NO retry. The button's whole job is an honest live
#: verdict — a retry that masks a blip is a false green. The admin re-clicks.
TEST_CONNECTION_POLICY: Final[RetryPolicy] = RetryPolicy(
    name="test_connection",
    transient_attempts=1,
    base_delay=0.0,
    max_delay=0.0,
    deadline=5.0,
)


# ---------------------------------------------------------------------------
# The retry seam
# ---------------------------------------------------------------------------


class DBConnectionFailed(Exception):
    """A connect handshake that officially failed after the retry budget.

    Carries the closed :class:`DBConnFailureCategory` and the *actual* number of
    attempts made (honest: a fail-fast auth error reports 1). The string form is
    intentionally credential-free — render an admin-facing explanation with
    :func:`render_admin_message`.
    """

    def __init__(
        self, category: DBConnFailureCategory, *, attempts_made: int
    ) -> None:
        self.category = category
        self.attempts_made = attempts_made
        super().__init__(
            f"DB connection failed ({category.value}) after "
            f"{attempts_made} attempt(s)"
        )


def _default_jitter(cap: float) -> float:
    """Full-jitter: uniform random in ``[0, cap]``."""
    if cap <= 0:
        return 0.0
    return random.uniform(0.0, cap)  # noqa: S311 - jitter, not crypto


async def connect_with_retry(
    acquire: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    classify_fn: Callable[[BaseException], DBConnFailureCategory] = classify,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    now: Callable[[], float] = time.monotonic,
    jitter: Callable[[float], float] = _default_jitter,
) -> T:
    """Run *acquire* with retry under *policy*; raise :class:`DBConnectionFailed`.

    ``acquire`` performs ONE connect handshake (e.g. open engine + ``SELECT 1``)
    and returns its result on success. On failure it must raise; the exception
    is classified and either retried (transient, budget remaining, within
    deadline) or surfaced as :class:`DBConnectionFailed`.

    All side-effecting dependencies are injected for offline testing:
    ``classify_fn`` / ``sleep`` / ``now`` / ``jitter``.

    Security: the original exception is dropped with ``from None`` — its raw
    text (possibly a DSN) never escapes on the chain.

    Note: ``deadline`` bounds retry *scheduling* — the seam will not start a
    backoff sleep that would cross it — not a single ``acquire()``, which may
    still run to its own connect timeout. Size each surface's connect timeout
    accordingly.
    """
    start = now()
    attempt = 0
    while True:
        attempt += 1
        try:
            return await acquire()
        except DBConnectionFailed:
            # Already classified+terminal (nested seam) — never wrap twice.
            raise
        except Exception as exc:  # noqa: BLE001 - classified + re-raised clean
            category = classify_fn(exc)
            max_attempts = policy.max_attempts_for(category)
            if attempt >= max_attempts:
                raise DBConnectionFailed(
                    category, attempts_made=attempt
                ) from None

            # Full-jitter backoff bounded by an exponential cap; never sleep
            # past the deadline — fail now rather than overshoot.
            exp_cap = min(
                policy.max_delay, policy.base_delay * (2 ** (attempt - 1))
            )
            delay = jitter(exp_cap)
            if (now() - start) + delay >= policy.deadline:
                raise DBConnectionFailed(
                    category, attempts_made=attempt
                ) from None
            await sleep(delay)


# ---------------------------------------------------------------------------
# Admin explanation (allowlist of constant sentences + leak tripwire)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdminMessage:
    """An admin-facing failure explanation. Never contains a DSN/credential.

    ``technical_detail`` is populated ONLY for :data:`DBConnFailureCategory.UNKNOWN`
    (redacted + truncated + tripwired); for every classified category the
    constant ``headline`` / ``next_action`` say everything safely.
    """

    category: DBConnFailureCategory
    headline: str
    next_action: str
    attempts_made: int
    technical_detail: str | None = None


#: Constant, allowlisted sentences per category. These are domain (ops)
#: knowledge, not UI copy, and are rendered server-side so background surfaces
#: (Celery study/sync, future notification email) get the identical wording.
_TEMPLATES: Final[dict[DBConnFailureCategory, tuple[str, str]]] = {
    DBConnFailureCategory.DB_UNREACHABLE: (
        "The database could not be reached.",
        "Confirm the database is running and reachable from the application "
        "network, then re-run this step.",
    ),
    DBConnFailureCategory.CONNECT_TIMEOUT: (
        "The database did not respond in time.",
        "Check network latency and firewall rules between the app and the "
        "database, then retry.",
    ),
    DBConnFailureCategory.SERVER_UNAVAILABLE: (
        "The database server is not accepting connections yet.",
        "Wait for the server to finish starting up or recovering, then retry.",
    ),
    DBConnFailureCategory.SERVER_OVERLOADED: (
        "The database has no connection slots available.",
        "Free up connections or raise the server's connection limit, then "
        "retry.",
    ),
    DBConnFailureCategory.AUTH_FAILED: (
        "The database rejected the credentials.",
        "Update the source's username and password, then re-test the "
        "connection. (Not retried — retrying a rejected login can lock the "
        "account.)",
    ),
    DBConnFailureCategory.PERMISSION_DENIED: (
        "The account lacks permission for this operation.",
        "Grant the account read access to the target database and schema, "
        "then retry.",
    ),
    DBConnFailureCategory.DATABASE_NOT_FOUND: (
        "The target database does not exist.",
        "Check the database name in the source configuration, then re-test.",
    ),
    DBConnFailureCategory.TLS_FAILED: (
        "The secure (TLS) handshake with the database failed.",
        "Check the TLS/SSL settings and certificates on both ends, then "
        "retry.",
    ),
    DBConnFailureCategory.UNKNOWN: (
        "The database connection failed for an unexpected reason.",
        "Check the server logs for details, then retry.",
    ),
}

#: Max length of the optional UNKNOWN technical_detail (redact happens BEFORE
#: truncation so a split can't defeat the redactor).
_MAX_DETAIL: Final[int] = 240

#: Fail-safe sentinel when the tripwire detects a residual leak.
_WITHHELD: Final[str] = "(technical details withheld to protect credentials)"

# --- leak tripwire patterns (defense-in-depth over the denylist redactor) ---
# Every pattern is linear (no nested unbounded quantifiers) and input is capped
# to _MAX_DETAIL chars before the tripwire runs, so there is no ReDoS surface.
# All matches fail SAFE to the withheld constant, so over-tripping is acceptable
# and intentional — we would rather blank a benign UNKNOWN detail than risk a
# host/credential/path fragment surviving the denylist redactor's known gaps.
_TRIPWIRE_URL_CRED: Final[re.Pattern[str]] = re.compile(r"://[^/\s]*@")
_TRIPWIRE_IPV4: Final[re.Pattern[str]] = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
#: Full IPv6 runs AND ``::``-compressed forms (``::1``, ``fe80::1``, ``2001:db8::1``).
_TRIPWIRE_IPV6: Final[re.Pattern[str]] = re.compile(
    r"(?:[0-9a-f]{1,4}:){2,}[0-9a-f]{1,4}|[0-9a-f]{0,4}::[0-9a-f:]*",
    re.IGNORECASE,
)
#: ODBC / alt connstring key spellings the denylist redactor does NOT cover.
#: Trips on key PRESENCE alone — the mere appearance of one of these keys means
#: a connection string fragment is present, regardless of how the value reads.
_TRIPWIRE_ALT_KV: Final[re.Pattern[str]] = re.compile(
    r"\b(pwd|uid|server|data source|initial catalog|trusted_connection|account)"
    r"\s*=",
    re.IGNORECASE,
)
#: Any multi-label dotted name (FQDN / bare hostname) the redactor leaves intact
#: because it has no port / scheme / kv form, e.g. ``db.internal.corp``. Also
#: trips on dotted driver class names (``psycopg2.OperationalError``) — that is
#: an accepted, fail-safe over-trip.
_TRIPWIRE_HOSTNAME: Final[re.Pattern[str]] = re.compile(
    r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+\b",
    re.IGNORECASE,
)
#: Unix socket / filesystem paths (≥2 segments), incl. the PG socket spelling.
_TRIPWIRE_FS_PATH: Final[re.Pattern[str]] = re.compile(r"(?:/[^/\s]+){2,}")


def _leaks(text: str) -> bool:
    """True if *text* still looks like it carries a host/credential/path fragment."""
    return bool(
        _TRIPWIRE_URL_CRED.search(text)
        or _TRIPWIRE_IPV4.search(text)
        or _TRIPWIRE_IPV6.search(text)
        or _TRIPWIRE_ALT_KV.search(text)
        or _TRIPWIRE_HOSTNAME.search(text)
        or _TRIPWIRE_FS_PATH.search(text)
    )


def safe_technical_detail(raw: object) -> str:
    """Redact → truncate → tripwire a raw error into admin-safe detail.

    Order is deliberate (see the security review): redact the COMPLETE string
    first (so every regex sees its anchors), then truncate the already-safe
    result, then run the tripwire as defense-in-depth — if anything host/
    credential-shaped survives, fail safe to a constant.
    """
    redacted = redact_dsn(raw)
    if len(redacted) > _MAX_DETAIL:
        redacted = redacted[: _MAX_DETAIL - 1].rstrip() + "…"
    if _leaks(redacted):
        return _WITHHELD
    return redacted


def render_admin_message(
    category: DBConnFailureCategory,
    *,
    attempts_made: int,
    technical_detail: object | None = None,
) -> AdminMessage:
    """Build an :class:`AdminMessage` from the constant template for *category*.

    Free-form ``technical_detail`` is attached ONLY for ``UNKNOWN`` (and is
    routed through :func:`safe_technical_detail`); every classified category
    relies on its constant sentences alone.
    """
    headline, next_action = _TEMPLATES.get(
        category, _TEMPLATES[DBConnFailureCategory.UNKNOWN]
    )
    detail: str | None = None
    if category is DBConnFailureCategory.UNKNOWN and technical_detail is not None:
        detail = safe_technical_detail(technical_detail)
    return AdminMessage(
        category=category,
        headline=headline,
        next_action=next_action,
        attempts_made=attempts_made,
        technical_detail=detail,
    )
