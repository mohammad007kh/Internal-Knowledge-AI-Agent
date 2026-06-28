"""Unit tests for the DB connect-retry core (Slice 0).

Fully offline: every external dependency of ``connect_with_retry`` is injected
(acquire / sleep / now / jitter / classify), so these tests need no database and
no real event-loop clock.
"""
from __future__ import annotations

import pytest

from src.services.db_safety.connect_retry import (
    BACKGROUND_POLICY,
    INTERACTIVE_POLICY,
    TEST_CONNECTION_POLICY,
    AdminMessage,
    DBConnectionFailed,
    DBConnFailureCategory,
    RetryPolicy,
    classify,
    connect_with_retry,
    is_permanent,
    render_admin_message,
    safe_technical_detail,
)

# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class _NamedError(Exception):
    """Helper to forge an exception whose type-name participates in matching."""


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # TLS / permanent
        ("SSL connection has been closed unexpectedly", DBConnFailureCategory.TLS_FAILED),
        ("certificate verify failed: self signed", DBConnFailureCategory.TLS_FAILED),
        # auth / permanent
        (
            'password authentication failed for user "cctp"',
            DBConnFailureCategory.AUTH_FAILED,
        ),
        ("Access denied for user 'root'@'localhost'", DBConnFailureCategory.AUTH_FAILED),
        ("Login failed for user 'sa'.", DBConnFailureCategory.AUTH_FAILED),
        ("AuthenticationFailed: bad auth", DBConnFailureCategory.AUTH_FAILED),
        # permission / permanent
        (
            "permission denied for table customers",
            DBConnFailureCategory.PERMISSION_DENIED,
        ),
        ("not authorized on admin to execute command", DBConnFailureCategory.PERMISSION_DENIED),
        # db-not-found / permanent
        ('database "shop" does not exist', DBConnFailureCategory.DATABASE_NOT_FOUND),
        ("Unknown database 'shop'", DBConnFailureCategory.DATABASE_NOT_FOUND),
        # overloaded / transient
        ("sorry, too many clients already", DBConnFailureCategory.SERVER_OVERLOADED),
        (
            "remaining connection slots are reserved",
            DBConnFailureCategory.SERVER_OVERLOADED,
        ),
        # unavailable / transient
        (
            "the database system is starting up",
            DBConnFailureCategory.SERVER_UNAVAILABLE,
        ),
        ("server closed the connection unexpectedly", DBConnFailureCategory.SERVER_UNAVAILABLE),
        # unreachable / transient
        ("connection refused", DBConnFailureCategory.DB_UNREACHABLE),
        (
            "could not translate host name to address: Name or service not known",
            DBConnFailureCategory.DB_UNREACHABLE,
        ),
        # unknown
        ("something totally unexpected happened", DBConnFailureCategory.UNKNOWN),
    ],
)
def test_classify_messages(message: str, expected: DBConnFailureCategory) -> None:
    assert classify(_NamedError(message)) is expected


def test_classify_timeout_by_type_even_with_empty_message() -> None:
    # TimeoutError carries no message yet must still classify by type;
    # asyncio.TimeoutError is an alias of TimeoutError on Python 3.11+.
    assert classify(TimeoutError()) is DBConnFailureCategory.CONNECT_TIMEOUT
    assert classify(_NamedError("operation timed out")) is (
        DBConnFailureCategory.CONNECT_TIMEOUT
    )


def test_classify_connection_refused_by_type() -> None:
    assert classify(ConnectionRefusedError()) is DBConnFailureCategory.DB_UNREACHABLE


def test_auth_beats_generic_connection_text() -> None:
    # A message containing BOTH "connection" and an auth signal must classify
    # as AUTH (permanent/specific wins over transient/generic).
    exc = _NamedError(
        "connection to server failed: password authentication failed for user x"
    )
    assert classify(exc) is DBConnFailureCategory.AUTH_FAILED


def test_role_missing_is_auth_not_database_not_found() -> None:
    # Regression: Postgres `role "x" does not exist` is an identity/auth failure,
    # NOT a missing database — must not fail-fast as permanent DATABASE_NOT_FOUND
    # with the wrong admin guidance.
    assert classify(_NamedError('FATAL:  role "cctp" does not exist')) is (
        DBConnFailureCategory.AUTH_FAILED
    )
    # ...while a genuinely missing database still classifies correctly.
    assert classify(_NamedError('database "shop" does not exist')) is (
        DBConnFailureCategory.DATABASE_NOT_FOUND
    )


# ---------------------------------------------------------------------------
# is_permanent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        DBConnFailureCategory.AUTH_FAILED,
        DBConnFailureCategory.PERMISSION_DENIED,
        DBConnFailureCategory.DATABASE_NOT_FOUND,
        DBConnFailureCategory.TLS_FAILED,
    ],
)
def test_permanent_categories(category: DBConnFailureCategory) -> None:
    assert is_permanent(category) is True


@pytest.mark.parametrize(
    "category",
    [
        DBConnFailureCategory.DB_UNREACHABLE,
        DBConnFailureCategory.CONNECT_TIMEOUT,
        DBConnFailureCategory.SERVER_UNAVAILABLE,
        DBConnFailureCategory.SERVER_OVERLOADED,
        DBConnFailureCategory.UNKNOWN,
    ],
)
def test_transient_categories(category: DBConnFailureCategory) -> None:
    assert is_permanent(category) is False


# ---------------------------------------------------------------------------
# RetryPolicy.max_attempts_for
# ---------------------------------------------------------------------------


def test_policy_permanent_is_one_attempt() -> None:
    assert BACKGROUND_POLICY.max_attempts_for(DBConnFailureCategory.AUTH_FAILED) == 1


def test_policy_transient_uses_configured_budget() -> None:
    assert (
        BACKGROUND_POLICY.max_attempts_for(DBConnFailureCategory.DB_UNREACHABLE) == 3
    )
    assert (
        INTERACTIVE_POLICY.max_attempts_for(DBConnFailureCategory.DB_UNREACHABLE) == 2
    )
    assert (
        TEST_CONNECTION_POLICY.max_attempts_for(
            DBConnFailureCategory.DB_UNREACHABLE
        )
        == 1
    )


def test_policy_override_can_reenable_retry_on_permanent() -> None:
    # Owner can flip any category's budget without a code change.
    policy = RetryPolicy(
        name="custom",
        transient_attempts=3,
        overrides={DBConnFailureCategory.AUTH_FAILED: 3},
    )
    assert policy.max_attempts_for(DBConnFailureCategory.AUTH_FAILED) == 3


def test_policy_overrides_are_defensively_copied_and_frozen() -> None:
    src = {DBConnFailureCategory.AUTH_FAILED: 3}
    policy = RetryPolicy(name="c", overrides=src)
    # Mutating the original dict must NOT bleed into the "frozen" policy.
    src[DBConnFailureCategory.AUTH_FAILED] = 99
    assert policy.max_attempts_for(DBConnFailureCategory.AUTH_FAILED) == 3
    # And the policy's own map is read-only.
    with pytest.raises(TypeError):
        policy.overrides[DBConnFailureCategory.TLS_FAILED] = 1  # type: ignore[index]


# ---------------------------------------------------------------------------
# connect_with_retry
# ---------------------------------------------------------------------------


def _recorder():
    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)

    return slept, sleep


@pytest.mark.asyncio
async def test_success_first_try_no_sleep() -> None:
    slept, sleep = _recorder()

    async def acquire() -> str:
        return "engine"

    result = await connect_with_retry(
        acquire, policy=BACKGROUND_POLICY, sleep=sleep, jitter=lambda c: 0.0
    )
    assert result == "engine"
    assert slept == []


@pytest.mark.asyncio
async def test_transient_then_success_retries() -> None:
    slept, sleep = _recorder()
    calls = {"n": 0}

    async def acquire() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionRefusedError("connection refused")
        return "ok"

    # now() advances by 0 so the deadline never trips; jitter returns the cap.
    result = await connect_with_retry(
        acquire,
        policy=BACKGROUND_POLICY,
        sleep=sleep,
        now=lambda: 0.0,
        jitter=lambda cap: cap,
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # slept before attempts 2 and 3


@pytest.mark.asyncio
async def test_permanent_fails_fast_one_attempt() -> None:
    slept, sleep = _recorder()
    calls = {"n": 0}

    async def acquire() -> str:
        calls["n"] += 1
        raise _NamedError("password authentication failed for user x")

    with pytest.raises(DBConnectionFailed) as ei:
        await connect_with_retry(
            acquire, policy=BACKGROUND_POLICY, sleep=sleep, jitter=lambda c: 0.0
        )
    assert ei.value.category is DBConnFailureCategory.AUTH_FAILED
    assert ei.value.attempts_made == 1
    assert calls["n"] == 1  # never retried
    assert slept == []


@pytest.mark.asyncio
async def test_transient_exhausts_budget() -> None:
    slept, sleep = _recorder()
    calls = {"n": 0}

    async def acquire() -> str:
        calls["n"] += 1
        raise ConnectionRefusedError("connection refused")

    with pytest.raises(DBConnectionFailed) as ei:
        await connect_with_retry(
            acquire,
            policy=BACKGROUND_POLICY,
            sleep=sleep,
            now=lambda: 0.0,
            jitter=lambda cap: 0.0,
        )
    assert ei.value.category is DBConnFailureCategory.DB_UNREACHABLE
    assert ei.value.attempts_made == 3
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_deadline_stops_before_budget() -> None:
    slept, sleep = _recorder()
    calls = {"n": 0}
    # Clock jumps 100s on the first read after start → deadline (20s) exceeded.
    ticks = iter([0.0, 100.0, 100.0, 100.0])

    async def acquire() -> str:
        calls["n"] += 1
        raise ConnectionRefusedError("connection refused")

    with pytest.raises(DBConnectionFailed) as ei:
        await connect_with_retry(
            acquire,
            policy=BACKGROUND_POLICY,
            sleep=sleep,
            now=lambda: next(ticks),
            jitter=lambda cap: cap,
        )
    # Deadline tripped on attempt 1's backoff computation → no sleep, 1 attempt.
    assert ei.value.attempts_made == 1
    assert slept == []


@pytest.mark.asyncio
async def test_chain_is_severed_no_cause_leak() -> None:
    async def acquire() -> str:
        raise _NamedError("connection refused to host=secret-db port=5432")

    with pytest.raises(DBConnectionFailed) as ei:
        await connect_with_retry(
            acquire,
            policy=TEST_CONNECTION_POLICY,
            now=lambda: 0.0,
            jitter=lambda c: 0.0,
        )
    # The raw driver exception (which embeds host/port) must NOT ride the chain.
    # __cause__ AND __context__ must both be clear — a chain-walking serializer
    # (Langfuse/Sentry) must not be able to recover the DSN off __context__.
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is True
    assert "secret-db" not in str(ei.value)


@pytest.mark.asyncio
async def test_nested_dbconnectionfailed_not_double_wrapped() -> None:
    inner = DBConnectionFailed(
        DBConnFailureCategory.AUTH_FAILED, attempts_made=1
    )

    async def acquire() -> str:
        raise inner

    with pytest.raises(DBConnectionFailed) as ei:
        await connect_with_retry(
            acquire, policy=BACKGROUND_POLICY, now=lambda: 0.0
        )
    assert ei.value is inner


# ---------------------------------------------------------------------------
# safe_technical_detail (redact → truncate → tripwire)
# ---------------------------------------------------------------------------


def test_safe_detail_redacts_dsn_url() -> None:
    raw = "could not connect: postgresql://user:p@ss@db.internal:5432/shop down"
    out = safe_technical_detail(raw)
    assert "user:p@ss" not in out
    assert "db.internal" not in out


def test_safe_detail_tripwire_catches_odbc_spelling() -> None:
    # redact_dsn (denylist) does NOT cover pwd=/server=; the tripwire must fail
    # safe to the withheld sentinel.
    raw = "[ODBC] Server=10.0.0.5;Database=shop;Uid=sa;Pwd=hunter2;"
    out = safe_technical_detail(raw)
    assert out == "(technical details withheld to protect credentials)"


def test_safe_detail_tripwire_catches_bare_ipv4() -> None:
    out = safe_technical_detail("connect failed to 192.168.1.50 after 3s")
    assert out == "(technical details withheld to protect credentials)"


@pytest.mark.parametrize(
    "raw",
    [
        # bare FQDN / hostname with NO port — slips redact_dsn entirely
        'could not translate host name "db.internal.corp" to address',
        # unix socket / filesystem paths
        "connect failed via /var/run/postgresql/.s.PGSQL.5432",
        "/var/run/postgresql socket missing",
        # IPv6 literal + ::-compressed forms
        "cannot reach ::1 loopback",
        "host 2001:db8::1 is unreachable",
    ],
)
def test_safe_detail_tripwire_withholds_topology(raw: str) -> None:
    # Defense-in-depth over redact_dsn's denylist gaps: any residual
    # host / path / IP fragment must fail safe to the withheld sentinel.
    assert safe_technical_detail(raw) == (
        "(technical details withheld to protect credentials)"
    )


def test_safe_detail_truncates_after_redaction() -> None:
    raw = "x" * 1000
    out = safe_technical_detail(raw)
    assert len(out) <= 240
    assert out.endswith("…")


def test_safe_detail_passes_clean_text() -> None:
    out = safe_technical_detail("query failed: relation reflection error")
    assert out == "query failed: relation reflection error"


# ---------------------------------------------------------------------------
# render_admin_message
# ---------------------------------------------------------------------------


def test_render_classified_uses_constants_no_detail() -> None:
    msg = render_admin_message(
        DBConnFailureCategory.AUTH_FAILED,
        attempts_made=1,
        technical_detail="password authentication failed for user secret",
    )
    assert isinstance(msg, AdminMessage)
    assert msg.headline == "The database rejected the credentials."
    assert msg.attempts_made == 1
    # Even though a raw detail was passed, a classified category never attaches
    # free text — the constants say everything safely.
    assert msg.technical_detail is None
    assert "secret" not in (msg.next_action + msg.headline)


def test_render_unknown_attaches_safe_detail() -> None:
    msg = render_admin_message(
        DBConnFailureCategory.UNKNOWN,
        attempts_made=3,
        technical_detail="weird driver error code 0x42",
    )
    assert msg.technical_detail == "weird driver error code 0x42"
    assert msg.attempts_made == 3


def test_render_unknown_without_detail_is_none() -> None:
    msg = render_admin_message(
        DBConnFailureCategory.UNKNOWN, attempts_made=2
    )
    assert msg.technical_detail is None
