"""Unit tests for ``GET /api/v1/sources/{id}/connection-config`` (FX7).

The endpoint powers the EditCredentialsDialog pre-fill. It returns ONLY the
non-secret connection metadata the admin already typed at creation
(db_type / host / port / database / username / ssl_mode / collection), plus
the SELECT ``query`` and a ``has_password`` flag — and NEVER the password or
the raw connection string/URI (which can embed the password).

Covered contract:

* 200 happy path — structured config → all the structured fields are
  returned and ``has_password=True``; the response body contains NO
  ``password`` key, no ``connection_string`` / ``uri`` and no URL.
* Legacy config (only a ``connection_string``) → it's parsed with
  ``sqlalchemy.engine.make_url`` and host/port/database/username are lifted
  from the URL with the password component DROPPED; ``has_password`` reflects
  whether the URL carried a password.
* 403 for a user who is neither the owner nor an admin (mirrors the
  ``PATCH /credentials`` authz).
* 400 for a non-database source; 404 for a missing source.
* An ``admin_audit_log`` row with ``action='source.connection_config_view'``
  and an empty metadata dict is written.

Reuses the ``_make_db_source`` / app-fixture shape from
``test_sources_credentials.py``; ``study_source.delay`` is stubbed because the
sources router imports the study task at module import time.
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
_STRANGER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000077")

# A structured config like the one ``_build_database_config`` persists after
# a credential rotation: structured fields + connection_string + password.
_STRUCTURED_CONFIG = {
    "db_type": "postgresql",
    "host": "reporting.internal",
    "port": 5432,
    "database": "analytics",
    "username": "report_ro",
    "password": "s3cret-do-not-leak",
    "connection_string": (
        "postgresql+asyncpg://report_ro:s3cret-do-not-leak@reporting.internal:5432/analytics"
    ),
    "query": "SELECT * FROM v_report",
    "ssl_mode": "require",
}

# A legacy config: only a connection string, no structured fields.
_LEGACY_CONFIG = {
    "connection_string": "postgresql://legacy_user:legacypw@legacy.host:6543/legacydb",
}


def _make_user(role: str, user_id: uuid.UUID) -> MagicMock:
    from src.models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = user_id
    u.email = f"{role}@example.com"
    u.role = UserRole.admin if role == "admin" else UserRole.user
    u.is_active = True
    return u


def _make_db_source() -> MagicMock:
    """A MagicMock standing in for a database Source ORM row."""
    from src.models.enums import SourceType

    src = MagicMock()
    src.id = _SOURCE_ID
    src.owner_id = _OWNER_ID
    src.source_type = SourceType.DATABASE
    src.name = "Reporting DB"
    return src


@pytest.fixture()
def db_session():
    m = MagicMock()
    m.commit = AsyncMock()
    m.execute = AsyncMock()
    return m


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, db_session):
    """FastAPI app wired with the sources router + overridden collaborators.

    ``SourceService.get_source`` / ``get_source_config`` and
    ``AdminAuditLogRepository.insert`` are stubbed; tests flip the stubs to
    exercise the legacy / non-DB / missing branches.
    """
    from fastapi import FastAPI

    from src.api.middleware.error_handler import register_exception_handlers
    from src.api.v1.sources import _get_source_service, router
    from src.core.database import get_db
    from src.core.deps import get_current_user
    from src.repositories.admin_audit_log_repository import AdminAuditLogRepository

    # study_source.delay — imported at router import time. Stub so nothing
    # reaches a broker (this endpoint never enqueues, but the import path is
    # shared with the credentials route).
    from src.tasks import study_source as _study_module  # noqa: PLC0415

    monkeypatch.setattr(
        _study_module.study_source, "delay", MagicMock(), raising=True
    )

    audit_insert = AsyncMock(return_value=None)
    monkeypatch.setattr(
        AdminAuditLogRepository, "insert", audit_insert, raising=True
    )

    service_stub = AsyncMock()
    service_stub.get_source = AsyncMock(return_value=_make_db_source())
    service_stub.get_source_config = AsyncMock(return_value=dict(_STRUCTURED_CONFIG))

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/sources")

    admin_user = _make_user("admin", _ADMIN_ID)
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[_get_source_service] = lambda: service_stub

    app.state._spies = {
        "service": service_stub,
        "audit_insert": audit_insert,
        "get_current_user_override": get_current_user,
    }
    return app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Forbidden-substring scanner — the single most important assertion.
#
# The body is allowed to carry the boolean key ``has_password`` (no value
# leak there), but NOT a key literally named ``password`` and NOT any of the
# secret values / raw-URL fragments below.
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    "s3cret-do-not-leak",  # the structured-config password VALUE
    "legacypw",  # the legacy-URL password VALUE
    "connection_string",
    "connection_uri",
    "://",  # no URL scheme separator anywhere in the body
)


def _assert_no_secrets(body_text: str) -> None:
    lowered = body_text.lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        assert needle not in lowered, (
            f"connection-config response leaked forbidden substring "
            f"{needle!r}: {body_text!r}"
        )
    # No JSON key literally named "password" (``has_password`` is fine).
    assert '"password"' not in lowered, (
        f"connection-config response contains a 'password' key: {body_text!r}"
    )


# ---------------------------------------------------------------------------
# Happy path — structured config
# ---------------------------------------------------------------------------


def test_structured_config_returns_metadata_and_has_password(app, client):
    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data == {
        "db_type": "postgresql",
        "host": "reporting.internal",
        "port": 5432,
        "database": "analytics",
        "username": "report_ro",
        "ssl_mode": "require",
        "collection": None,
        "query": "SELECT * FROM v_report",
        "has_password": True,
    }
    # The body never contains the password or any raw connection string/URL.
    _assert_no_secrets(resp.text)


def test_audit_row_written_for_config_view(app, client):
    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text

    spies = app.state._spies
    spies["audit_insert"].assert_awaited_once()
    kwargs = spies["audit_insert"].await_args.kwargs
    assert kwargs["action"] == "source.connection_config_view"
    assert kwargs["resource_type"] == "source"
    assert kwargs["resource_id"] == _SOURCE_ID
    # Metadata is empty — we record THAT the config was viewed, not its values.
    assert kwargs["metadata"] == {}


# ---------------------------------------------------------------------------
# Legacy config — only a connection_string
# ---------------------------------------------------------------------------


def test_legacy_connection_string_is_parsed_with_password_dropped(app, client):
    spies = app.state._spies
    spies["service"].get_source_config.return_value = dict(_LEGACY_CONFIG)

    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["host"] == "legacy.host"
    assert data["port"] == 6543
    assert data["database"] == "legacydb"
    assert data["username"] == "legacy_user"
    assert data["db_type"] == "postgresql"  # mapped from the URL drivername
    # The legacy URL carried a password → has_password must reflect that...
    assert data["has_password"] is True
    # ...but the password itself is GONE from the response.
    _assert_no_secrets(resp.text)


def test_legacy_connection_string_without_password(app, client):
    spies = app.state._spies
    spies["service"].get_source_config.return_value = {
        "connection_string": "mysql://anon@db.host:3306/app",
    }

    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["db_type"] == "mysql"
    assert data["host"] == "db.host"
    assert data["port"] == 3306
    assert data["database"] == "app"
    assert data["username"] == "anon"
    assert data["has_password"] is False
    _assert_no_secrets(resp.text)


def test_empty_config_returns_all_null_shape(app, client):
    spies = app.state._spies
    spies["service"].get_source_config.return_value = {}

    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == {
        "db_type": None,
        "host": None,
        "port": None,
        "database": None,
        "username": None,
        "ssl_mode": None,
        "collection": None,
        "query": None,
        "has_password": False,
    }


# ---------------------------------------------------------------------------
# Authz — owner-or-admin, mirroring PATCH /credentials
# ---------------------------------------------------------------------------


def test_owner_can_read_own_source_config(app, client):
    """A non-admin who OWNS the source is allowed (matches PATCH/credentials)."""
    spies = app.state._spies
    app.dependency_overrides[spies["get_current_user_override"]] = lambda: _make_user(
        "owner", _OWNER_ID
    )
    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 200, resp.text


def test_stranger_gets_403(app, client):
    """Neither owner nor admin → 403; no audit row."""
    spies = app.state._spies
    app.dependency_overrides[spies["get_current_user_override"]] = lambda: _make_user(
        "user", _STRANGER_ID
    )
    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 403, resp.text
    spies["audit_insert"].assert_not_awaited()


# ---------------------------------------------------------------------------
# DB-only gating + missing source
# ---------------------------------------------------------------------------


def test_non_database_source_returns_400(app, client):
    from src.models.enums import SourceType

    spies = app.state._spies
    file_source = _make_db_source()
    file_source.source_type = SourceType.FILE_UPLOAD
    spies["service"].get_source.return_value = file_source

    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 400, resp.text
    assert "database sources" in resp.json()["detail"]["detail"]
    spies["service"].get_source_config.assert_not_awaited()
    spies["audit_insert"].assert_not_awaited()


def test_missing_source_returns_404(app, client):
    from src.core.exceptions import NotFoundError

    spies = app.state._spies
    spies["service"].get_source.side_effect = NotFoundError(
        f"Source {_SOURCE_ID} not found.",
    )
    resp = client.get(f"/sources/{_SOURCE_ID}/connection-config")
    assert resp.status_code == 404, resp.text
    spies["audit_insert"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Response model is strict
# ---------------------------------------------------------------------------


def test_response_model_forbids_extra_fields() -> None:
    """``extra='forbid'`` is the structural guard against leaking new keys."""
    from pydantic import ValidationError

    from src.api.v1.sources import SourceConnectionConfigResponse

    with pytest.raises(ValidationError):
        SourceConnectionConfigResponse.model_validate(
            {"host": "x", "password": "leak", "has_password": True}
        )


def test_extract_helper_drops_password_and_url() -> None:
    """The extraction helper never copies a password or connection string."""
    from src.api.v1.sources import _extract_connection_config

    out = _extract_connection_config(dict(_STRUCTURED_CONFIG))
    dumped = out.model_dump()
    assert "password" not in dumped
    assert "connection_string" not in dumped
    assert all("://" not in str(v) for v in dumped.values() if isinstance(v, str))
    assert out.has_password is True
