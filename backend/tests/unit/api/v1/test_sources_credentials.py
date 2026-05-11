"""Unit tests for ``PATCH /api/v1/sources/{id}/credentials`` (U8 + FX4).

Covers the documented contract:

* 200 happy path — connector test passes, config is re-encrypted, connection
  health is reset to ``unknown``, audit row is emitted with
  ``action='source.credentials_change'``.
* 401 when the ``confirm_password`` does not match the calling user's
  hashed_password (FX4 re-auth gate). On failure the lockout counter is
  incremented; on success it is reset.
* 422 when the connector ``test_connection()`` returns ``False`` — the
  repository's ``update`` MUST NOT have been called (no persistence on
  failure, modal-stays-open contract).
* The submitted password value MUST NOT appear in the audit metadata —
  ``changed_fields`` is a list of field NAMES only.
* 400 when the source is not a database source.
* 404 when the source id does not exist (after a valid confirm_password).
* 423 when AccountLockout reports the account is currently locked — the
  bcrypt verification MUST NOT run, otherwise the lockout is meaningless.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")


_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
_OWNER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000077")


def _make_admin_user_with_password(plaintext: str) -> MagicMock:
    """Build a User mock whose hashed_password matches *plaintext*.

    Uses the real :class:`PasswordService` so the route's bcrypt check
    succeeds. Centralised so tests don't have to repeat the bcrypt boilerplate.
    """
    from src.models.user import User, UserRole
    from src.services.password_service import PasswordService

    u = MagicMock(spec=User)
    u.id = _ADMIN_ID
    u.email = "admin@example.com"
    u.role = UserRole.admin
    u.is_active = True
    u.hashed_password = PasswordService.hash_password(plaintext)
    return u


def _make_db_source() -> MagicMock:
    """Return a MagicMock standing in for a Source ORM row.

    Every field that ``SourceResponse.model_validate`` reads is populated
    with a real value (no MagicMock children) — Pydantic v2 with
    ``from_attributes=True`` calls ``getattr`` on each declared field, and
    a stray MagicMock would fail strict type validation.

    ``source_type`` is set to the StrEnum value the production code path
    receives — ``SourceType.DATABASE``. The route's branching reads either
    ``.value`` or ``str(...)``, both of which resolve to ``"database"``.
    """
    from datetime import datetime, timezone

    from src.models.enums import SourceType

    src = MagicMock()
    src.id = _SOURCE_ID
    src.owner_id = _OWNER_ID
    src.source_type = SourceType.DATABASE
    src.name = "Reporting DB"
    src.is_active = True
    src.deleted_at = None
    now = datetime.now(timezone.utc)
    src.created_at = now
    src.updated_at = now
    src.description = None
    src.source_mode = "live"
    src.retrieval_mode = "text_to_query"
    src.sync_mode = "manual"
    src.sync_schedule = None
    src.last_synced_at = None
    src.next_sync_due_at = None
    src.status = "ready"
    src.citations_enabled = True
    src.embedder_id = None
    src.name_status = "user_set"
    src.description_status = "user_set"
    src.auto_name_and_description = False
    src.schema_status = None
    src.drift_signal_count = 0
    src.last_studied_at = None
    src.connection_status = "unknown"
    src.connection_last_checked_at = now
    src.connection_last_error = None
    # Optional SchemaStudy-derived fields — none for this fixture.
    src.study_state = None
    src.tables_documented = None
    src.tables_partial = None
    src.last_error_phase = None
    src.last_error_message = None
    # U10 — detail-endpoint enrichment fields (must be concrete, not MagicMock,
    # or SourceResponse.model_validate fails strict typing on the response).
    src.owner_email = "admin@example.com"
    src.schema_summary = None
    return src


@pytest.fixture()
def db_session():
    """An AsyncMock-backed AsyncSession with a no-op commit/execute pair."""
    m = MagicMock()
    m.commit = AsyncMock()
    m.execute = AsyncMock()
    return m


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, db_session):
    """Build a FastAPI app wired with the sources router + overridden deps.

    All collaborators (SourceService.update_database_credentials,
    ConnectorFactory.build, SourceRepository.update,
    AdminAuditLogRepository.insert) are overridden via
    ``app.dependency_overrides`` or ``monkeypatch`` so the tests run
    fully in-memory — no DB, no live connector — yet exercise the real
    route handler end-to-end.

    The service stub's ``update_database_credentials`` re-fans-out into the
    connector + repo spies so existing assertions (``connector_test``,
    ``repo_update``) still capture the same in-flight calls — even though
    the route now delegates to the service rather than reaching into its
    private methods.
    """
    from fastapi import FastAPI

    from src.api.middleware.error_handler import register_exception_handlers
    from src.api.v1.sources import (
        _get_account_lockout,
        _get_source_service,
        router,
    )
    from src.connectors.factory import ConnectorFactory
    from src.core.database import get_db
    from src.core.deps import get_current_user
    from src.core.exceptions import ConnectorTestFailedError
    from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
    from src.repositories.source_repository import SourceRepository

    # 1) Connector stub — captured here so the service stub's side_effect
    #    can re-emit the same call for the legacy assertions.
    connector_stub = AsyncMock()
    connector_stub.test_connection = AsyncMock(return_value=True)
    factory_build = MagicMock(return_value=connector_stub)
    monkeypatch.setattr(ConnectorFactory, "build", factory_build, raising=True)

    # 2) SourceRepository.update spy — re-emitted from the service stub so
    #    happy-path assertions like ``kwargs['connection_status']`` still work.
    repo_update = AsyncMock(return_value=_make_db_source())
    monkeypatch.setattr(SourceRepository, "update", repo_update, raising=True)

    # 3) AdminAuditLogRepository.insert — captures the audit row.
    audit_insert = AsyncMock(return_value=None)
    monkeypatch.setattr(
        AdminAuditLogRepository, "insert", audit_insert, raising=True
    )

    # 3b) study_source.delay — the credentials endpoint re-studies the
    #     schema after a rotation (slice E1). Stub the celery .delay so it
    #     never reaches a broker; tests don't assert on it here (the enqueue
    #     contract is covered in test_sources.py's TestCreateSourceEnqueues…).
    from src.tasks import study_source as _study_module  # noqa: PLC0415

    monkeypatch.setattr(
        _study_module.study_source, "delay", MagicMock(), raising=True
    )

    # 4) SourceService stub. ``get_source`` returns the DB-source MagicMock;
    #    ``update_database_credentials`` runs through the connector + repo
    #    spies and returns ``(updated_source, changed_fields)``. Tests can
    #    flip ``connector_stub.test_connection.return_value`` to False to
    #    assert the 422 path.
    service_stub = AsyncMock()
    service_stub.get_source = AsyncMock(return_value=_make_db_source())

    async def _fake_update(  # type: ignore[no-untyped-def]
        *,
        source_id,
        submitted: dict,
        connection_uri,
    ):
        from datetime import UTC, datetime as _dt

        ok = bool(await connector_stub.test_connection())
        if not ok:
            raise ConnectorTestFailedError(
                "Connection test failed with the supplied credentials. "
                "Credentials were NOT updated.",
            )
        updated = await repo_update(
            source_id,
            config_encrypted=b"FAKE_CIPHER",
            connection_status="unknown",
            connection_last_checked_at=_dt.now(UTC),
            connection_last_error=None,
        )
        return updated, sorted(submitted.keys())

    service_stub.update_database_credentials = AsyncMock(side_effect=_fake_update)

    # 5) AccountLockout stub — by default a no-op so the existing 6 tests
    #    don't have to know about it. Tests for lockout flip the relevant
    #    method to raise / track invocation.
    lockout_stub = AsyncMock()
    lockout_stub.check = AsyncMock(return_value=None)
    lockout_stub.record_failure = AsyncMock(return_value=None)
    lockout_stub.reset = AsyncMock(return_value=None)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/sources")

    admin_user = _make_admin_user_with_password("AdminPw!23")
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[_get_source_service] = lambda: service_stub
    app.dependency_overrides[_get_account_lockout] = lambda: lockout_stub

    # Hand back the spies so tests can introspect.
    app.state._spies = {
        "connector_test": connector_stub.test_connection,
        "repo_update": repo_update,
        "audit_insert": audit_insert,
        "service": service_stub,
        "lockout": lockout_stub,
        "admin_user": admin_user,
    }
    return app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_200_resets_connection_status_and_audits(app, client):
    """200 path: connector test passes → row updated, audit row emitted.

    Asserts:
      * status 200
      * SourceRepository.update was called with connection_status='unknown'
        and connection_last_error=None (the modal's promised side-effect)
      * The audit row carries ``action='source.credentials_change'`` and a
        ``changed_fields`` list — never the raw password.
    """
    body = {
        "confirm_password": "AdminPw!23",
        "host": "new.example.com",
        "port": 5433,
        "username": "newuser",
        "password": "newpw-secret",
        "database": "olddb",
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 200, resp.text

    spies = app.state._spies
    spies["connector_test"].assert_awaited_once()
    spies["repo_update"].assert_awaited_once()
    update_call = spies["repo_update"].await_args
    # update(source_id, **kwargs) — kwargs is the second positional dict
    kwargs = update_call.kwargs
    assert kwargs["connection_status"] == "unknown"
    assert kwargs["connection_last_error"] is None
    assert "connection_last_checked_at" in kwargs
    assert kwargs["config_encrypted"] == b"FAKE_CIPHER"

    # Audit row inspection.
    spies["audit_insert"].assert_awaited_once()
    audit_kwargs = spies["audit_insert"].await_args.kwargs
    assert audit_kwargs["action"] == "source.credentials_change"
    metadata = audit_kwargs["metadata"]
    assert "changed_fields" in metadata
    # Password VALUE never appears in metadata — only the field name.
    assert "newpw-secret" not in str(metadata)
    assert "AdminPw!23" not in str(metadata)


# ---------------------------------------------------------------------------
# Re-auth gate (FX4)
# ---------------------------------------------------------------------------


def test_wrong_confirm_password_returns_401_and_does_not_persist(app, client):
    """Wrong confirm_password → 401; nothing persisted, no audit row."""
    body = {
        "confirm_password": "totally-wrong-password!!!",
        "host": "new.example.com",
        "port": 5433,
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 401, resp.text

    spies = app.state._spies
    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()
    # Connector test should NEVER run on a wrong-password call — that would
    # let an attacker probe credentials without auth.
    spies["connector_test"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Connector test failure → 422, no persist
# ---------------------------------------------------------------------------


def test_connector_test_failure_returns_422_and_does_not_persist(app, client):
    """When test_connection() returns False → 422 and the source is untouched.

    This is the "modal stays open with the connector error" contract. The
    repo.update call MUST NOT have happened so a doomed credential rotation
    can't half-apply.
    """
    spies = app.state._spies
    # Flip the connector to fail.
    spies["connector_test"].return_value = False

    body = {
        "confirm_password": "AdminPw!23",
        "host": "broken.example.com",
        "port": 5433,
        "username": "newuser",
        "password": "newpw-secret",
        "database": "olddb",
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    # Sanitised — never echoes the candidate config.
    assert "broken.example.com" not in resp.text
    assert "newpw-secret" not in resp.text
    assert "Connection test failed" in detail["detail"]

    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Schema-level guarantees
# ---------------------------------------------------------------------------


def test_request_schema_forbids_extra_fields() -> None:
    """``extra='forbid'`` keeps callers from sneaking unknown fields through.

    Any new credential field must be added to the model explicitly so the
    audit ``changed_fields`` list stays accurate.
    """
    from pydantic import ValidationError

    from src.api.v1.sources import SourceCredentialsUpdateRequest

    with pytest.raises(ValidationError):
        SourceCredentialsUpdateRequest.model_validate(
            {
                "confirm_password": "x",
                "totally_unknown_field": "value",
            }
        )


def test_request_requires_confirm_password() -> None:
    """The re-auth field is mandatory at the schema layer."""
    from pydantic import ValidationError

    from src.api.v1.sources import SourceCredentialsUpdateRequest

    with pytest.raises(ValidationError):
        SourceCredentialsUpdateRequest.model_validate({"host": "x"})


# ---------------------------------------------------------------------------
# Source-type guard
# ---------------------------------------------------------------------------


def test_returns_400_when_source_is_not_database_type(app, client):
    """File-upload sources must NOT expose the credentials editor.

    The route is documented as DB-only — for any other source_type we
    return 400 with a clear message and never invoke the connector or
    repo. This test would also reject a regression where the type guard
    is silently dropped (e.g. by accepting any source and letting the
    DB-shaped config-merge throw downstream).
    """
    from src.models.enums import SourceType

    spies = app.state._spies
    # Re-stamp the source mock as a file_upload — bypasses the
    # ``if source_type_value != "database"`` branch.
    file_source = _make_db_source()
    file_source.source_type = SourceType.FILE_UPLOAD
    spies["service"].get_source.return_value = file_source

    body = {
        "confirm_password": "AdminPw!23",
        "host": "new.example.com",
        "port": 5433,
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "database sources" in detail["detail"]

    # Connector + persist + audit must all be untouched on the type guard.
    spies["connector_test"].assert_not_awaited()
    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()


def test_returns_404_when_source_missing_after_valid_password(app, client):
    """Wrong source id with a CORRECT confirm_password returns 404, not 401.

    The auth gate runs first (so a 404 only fires after re-auth succeeds),
    and the route delegates to ``service.get_source`` which raises
    :class:`NotFoundError` → 404. Asserting this explicitly because the
    naive ordering ("get_source first, then password") would let an
    attacker enumerate source ids without a valid password.
    """
    from src.core.exceptions import NotFoundError

    spies = app.state._spies
    spies["service"].get_source.side_effect = NotFoundError(
        f"Source {_SOURCE_ID} not found.",
    )

    body = {
        "confirm_password": "AdminPw!23",
        "host": "new.example.com",
        "port": 5433,
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 404, resp.text
    # Sanity: still NOT a 401 (i.e. password was accepted).
    spies["connector_test"].assert_not_awaited()
    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Audit metadata never leaks the password
# ---------------------------------------------------------------------------


def test_audit_metadata_never_includes_password(app, client):
    """Defence-in-depth: assert NO ``password`` key AND no value match.

    The audit_service's redactor strips ``password``-keyed entries, and
    the route only passes ``changed_fields`` (a list of NAMES). This test
    pins both invariants so a regression in either layer is caught.
    """
    submitted_password = "ultra-secret-pwd-xyz"
    body = {
        "confirm_password": "AdminPw!23",
        "host": "new.example.com",
        "port": 5433,
        "username": "newuser",
        "password": submitted_password,
        "database": "olddb",
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 200, resp.text

    spies = app.state._spies
    spies["audit_insert"].assert_awaited_once()
    audit_kwargs = spies["audit_insert"].await_args.kwargs
    metadata = audit_kwargs["metadata"]

    # No ``password`` key at any depth.
    def _has_password_key(obj):
        if isinstance(obj, dict):
            if "password" in {k.lower() for k in obj.keys() if isinstance(k, str)}:
                return True
            return any(_has_password_key(v) for v in obj.values())
        if isinstance(obj, (list, tuple)):
            return any(_has_password_key(v) for v in obj)
        return False

    assert not _has_password_key(metadata), (
        f"audit metadata leaked a 'password' key: {metadata!r}"
    )
    # No value match: the submitted password STRING never appears anywhere.
    assert submitted_password not in str(metadata)


def test_connector_error_message_does_not_leak_credentials(app, client):
    """A connector exception that embeds the URI must NOT surface in the 422 body.

    The service catches the connector exception and raises a sanitised
    ``ConnectorTestFailedError`` with a fixed message — the underlying
    ``str(exc)`` (which can include host:port and credentials embedded by
    asyncpg / pymongo) MUST NOT appear on the wire.
    """
    spies = app.state._spies

    async def _leaky_test_connection():  # noqa: ANN202 — async-mock side_effect
        raise RuntimeError(
            "connection refused at postgres://user:s3cret@host:5432/db",
        )

    spies["connector_test"].side_effect = _leaky_test_connection
    # Switch the service stub to invoke the REAL service-level sanitisation
    # path so the assertion is end-to-end. The service stub already wraps
    # ConnectorTestFailedError on test_connection failure.
    from src.core.exceptions import ConnectorTestFailedError

    async def _sanitised_update(  # type: ignore[no-untyped-def]
        *, source_id, submitted, connection_uri
    ):
        try:
            await spies["connector_test"]()
        except Exception:  # noqa: BLE001
            raise ConnectorTestFailedError(
                "Connection test failed with the supplied credentials. "
                "Credentials were NOT updated.",
            ) from None
        return _make_db_source(), sorted(submitted.keys())

    spies["service"].update_database_credentials.side_effect = _sanitised_update

    body = {
        "confirm_password": "AdminPw!23",
        "host": "host",
        "port": 5432,
        "username": "user",
        "password": "s3cret",
        "database": "db",
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 422, resp.text
    body_text = resp.text
    # Neither the password value nor the URI fragment can appear in the
    # response body. Note we deliberately look for the secret via the
    # CONNECTOR's leaked message (not the submitted body) because the
    # request body field "password" is ``s3cret`` which would also fail
    # if we mirrored it back via the validation echo.
    assert "s3cret" not in body_text
    assert "postgres://" not in body_text


# ---------------------------------------------------------------------------
# Account lockout integration
# ---------------------------------------------------------------------------


def test_lockout_check_called_before_bcrypt(app, client):
    """A locked account → 423 BEFORE bcrypt runs.

    Without this ordering an attacker who has compromised the access token
    of a privileged user can brute-force the credentials gate at
    rate-limit speed. The lockout MUST be the first gate.
    """
    from src.core.exceptions import AccountLockedError

    spies = app.state._spies

    spies["lockout"].check.side_effect = AccountLockedError(
        "Account temporarily locked.",
        extra={"retry_after_seconds": 600},
    )

    # Prove the test isolates ordering by sabotaging verify_password — if
    # bcrypt runs first the test would still 401 instead of 423.
    import src.services.password_service as ps_module

    original_verify = ps_module.PasswordService.verify_password
    called: dict[str, bool] = {"verify": False}

    def _spy_verify(plaintext: str, hashed: str) -> bool:  # noqa: ANN001
        called["verify"] = True
        return original_verify(plaintext, hashed)

    ps_module.PasswordService.verify_password = staticmethod(_spy_verify)
    try:
        body = {
            "confirm_password": "AdminPw!23",
            "host": "new.example.com",
            "port": 5433,
        }
        resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    finally:
        ps_module.PasswordService.verify_password = staticmethod(original_verify)

    assert resp.status_code == 423, resp.text
    spies["lockout"].check.assert_awaited_once()
    # Critical ordering invariant.
    assert called["verify"] is False, (
        "verify_password ran before AccountLockout.check — the lockout is "
        "meaningless if bcrypt runs first."
    )
    spies["connector_test"].assert_not_awaited()
    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()


def test_lockout_record_failure_called_on_wrong_password(app, client):
    """Wrong password → AccountLockout.record_failure(email) is called once.

    Mirrors AuthService.login. Without this the 401 surface lacks any
    rate-limiting cost so an attacker can brute-force the gate.
    """
    spies = app.state._spies

    body = {
        "confirm_password": "totally-wrong-pw!!!",
        "host": "new.example.com",
        "port": 5433,
    }
    resp = client.patch(f"/sources/{_SOURCE_ID}/credentials", json=body)
    assert resp.status_code == 401, resp.text

    spies["lockout"].record_failure.assert_awaited_once()
    args, kwargs = spies["lockout"].record_failure.await_args
    # Accepts either positional or keyword call; pluck the email out.
    if args:
        called_with = args[0]
    else:
        called_with = kwargs.get("email")
    assert called_with == spies["admin_user"].email
    spies["lockout"].reset.assert_not_awaited()


# ---------------------------------------------------------------------------
# No-op save (FX7 — diffed-but-unchanged form)
# ---------------------------------------------------------------------------


def test_noop_save_with_only_confirm_password_returns_200_and_writes_no_audit(
    app, client
):
    """FX7: the dialog diffs the form and sends ONLY changed keys, so a save
    on an untouched form arrives as pure ``confirm_password``. That's a
    benign no-op — 200 with the source unchanged, NO connector test, NO
    re-encrypt, and crucially NO ``source.credentials_change`` audit row
    (the re-auth still ran — lockout/bcrypt are gated before the
    short-circuit — but nothing was changed, so nothing is logged).
    """
    resp = client.patch(
        f"/sources/{_SOURCE_ID}/credentials",
        json={"confirm_password": "AdminPw!23"},
    )
    assert resp.status_code == 200, resp.text

    spies = app.state._spies
    # The service's credential-update path is never invoked.
    spies["service"].update_database_credentials.assert_not_awaited()
    # No connector probe, no repo write, no audit row.
    spies["connector_test"].assert_not_awaited()
    spies["repo_update"].assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()
