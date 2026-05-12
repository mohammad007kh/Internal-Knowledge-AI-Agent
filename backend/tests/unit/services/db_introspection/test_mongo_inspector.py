"""Unit tests for the MongoDB schema inspector (studying-agent, schema-on-read).

``motor`` / ``pymongo`` / ``mongomock`` are not installed in this
environment, so these tests drive a **hand-rolled fake motor client** (see
:class:`_FakeMotorClient`) injected via the ``_client_factory`` test seam.
Real-Mongo behaviour (BSON edge cases, server-side ``find`` semantics) is
therefore *unverified* here — it's covered by the explicit type-inference
unit tests below plus the contract-level assertions on the assembled
``SchemaDocument``.

What's covered:

* INVENTORY discovers collections (``system.*`` skipped, optional single-
  collection filter honoured).
* COLUMNS unions the sampled docs' top-level keys, infers types,
  ``inferred=True`` + ``nullable=True`` on every field, ``_id`` → primary key.
* SAMPLING returns ≤3 PII-redacted distinct values; an ``email`` field is
  redacted + flagged ``is_pii_candidate``; BSON-binary fields are skipped.
* DESCRIBING is invoked per-collection + once for the summary (mocked LLM).
* A per-collection COLUMNS failure → PhaseError + partial, study continues.
* A per-collection SAMPLING failure → PhaseError + partial.
* No resolver → DESCRIBING skipped + partial (``LLM_UNAVAILABLE``).
* The assembled SchemaDocument validates strictly; ``dialect == "mongodb"``;
  the fingerprint is non-empty.
* The motor-driver-missing path raises ``SchemaStudyPhaseError(phase=
  'CONNECTING', error_key='MONGO_DRIVER_MISSING')``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# A tiny fake motor client (async surface used by mongo_inspector only)
# ---------------------------------------------------------------------------


class _FakeObjectId:
    """Stand-in for ``bson.ObjectId`` — class name is what the inspector checks."""

    def __init__(self, hex_str: str = "507f1f77bcf86cd799439011") -> None:
        self._hex = hex_str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self._hex


# Make ``type(x).__name__`` == "ObjectId" so _is_objectid() matches.
_FakeObjectId.__name__ = "ObjectId"


class _FakeBinary(bytes):
    """Stand-in for ``bson.Binary`` (subclasses bytes, named "Binary")."""


_FakeBinary.__name__ = "Binary"


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._limit: int | None = None

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = n
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = self._docs
        cap = self._limit if self._limit is not None else length
        if cap is not None:
            docs = docs[:cap]
        return list(docs)


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]], *, find_error: Exception | None = None) -> None:
        self._docs = docs
        self._find_error = find_error

    def find(self, *_args: Any, **_kwargs: Any) -> _FakeCursor:
        if self._find_error is not None:
            raise self._find_error
        return _FakeCursor(self._docs)


class _FakeDatabase:
    def __init__(
        self,
        collections: dict[str, list[dict[str, Any]]],
        *,
        ping_error: Exception | None = None,
        list_error: Exception | None = None,
        find_errors: dict[str, Exception] | None = None,
    ) -> None:
        self._collections = collections
        self._ping_error = ping_error
        self._list_error = list_error
        self._find_errors = find_errors or {}

    async def command(self, name: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if name == "ping":
            if self._ping_error is not None:
                raise self._ping_error
            return {"ok": 1}
        return {"ok": 1}  # pragma: no cover - only ping is used

    async def list_collection_names(self) -> list[str]:
        if self._list_error is not None:
            raise self._list_error
        return list(self._collections.keys())

    def __getitem__(self, collection: str) -> _FakeCollection:
        return _FakeCollection(
            self._collections.get(collection, []),
            find_error=self._find_errors.get(collection),
        )


class _FakeMotorClient:
    def __init__(self, db: _FakeDatabase) -> None:
        self._db = db
        self.closed = False

    def __getitem__(self, _database: str) -> _FakeDatabase:
        return self._db

    def close(self) -> None:
        self.closed = True


def _factory_for(db: _FakeDatabase):
    """Return a ``_client_factory`` (``uri -> client``) yielding a fake client.

    Captures the produced client so the test can assert ``close()`` ran.
    """
    produced: list[_FakeMotorClient] = []

    def _factory(_uri: str) -> _FakeMotorClient:
        client = _FakeMotorClient(db)
        produced.append(client)
        return client

    return _factory, produced


# ---------------------------------------------------------------------------
# A stub AIModelResolver (same shape as test_sql_inspector's)
# ---------------------------------------------------------------------------


def _stub_resolver() -> tuple[Any, AsyncMock]:
    create_mock = AsyncMock()

    async def _create(**kwargs: Any) -> Any:
        fmt_name = kwargs["response_format"]["json_schema"]["name"]
        if fmt_name == "corpus_summary":
            content = '{"summary": "This database stores users and audit events."}'
        else:
            content = (
                '{"description": "Holds documents for this collection.", '
                '"tags": ["document_store"]}'
            )
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    create_mock.side_effect = _create

    http_client = MagicMock()
    http_client.chat.completions.create = create_mock

    client = MagicMock()
    client.model_id = "gpt-test"
    client.temperature = 0.0
    client.max_tokens = 256
    client.http_client = http_client

    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=client)
    return resolver, create_mock


# ---------------------------------------------------------------------------
# Fixtures: a couple of collections with mixed-shape docs
# ---------------------------------------------------------------------------


def _sample_db() -> _FakeDatabase:
    users = [
        {
            "_id": _FakeObjectId("a" * 24),
            "email": "alice@example.com",
            "age": 30,
            "active": True,
            "score": 9.5,
            "joined": datetime(2024, 1, 10, tzinfo=timezone.utc),
            "tags": ["admin", "beta"],
            "profile": {"city": "NYC"},
            "avatar": _FakeBinary(b"\xde\xad\xbe\xef"),
        },
        {
            "_id": _FakeObjectId("b" * 24),
            "email": "bob@example.com",
            "age": 41,
            "active": False,
            "joined": datetime(2024, 2, 15, tzinfo=timezone.utc),
            # no 'score', no 'tags' for this doc — exercises nullable/union.
            "profile": {"city": "LA"},
            "avatar": _FakeBinary(b"\xca\xfe\xba\xbe"),
        },
        {
            "_id": _FakeObjectId("c" * 24),
            "email": "carol@example.com",
            "age": 22,
            "active": True,
            "score": 7.0,
            "joined": datetime(2024, 3, 20, tzinfo=timezone.utc),
            "tags": ["beta"],
            "profile": {"city": "SF"},
            "avatar": _FakeBinary(b"\x00\x11"),
        },
    ]
    audit_logs = [
        {"_id": _FakeObjectId("d" * 24), "action": "login", "ok": True},
        {"_id": _FakeObjectId("e" * 24), "action": "logout", "ok": True},
    ]
    return _FakeDatabase(
        {
            "users": users,
            "audit_logs": audit_logs,
            "system.profile": [{"_id": _FakeObjectId(), "junk": 1}],
        }
    )


# ---------------------------------------------------------------------------
# Tests — full pipeline
# ---------------------------------------------------------------------------


async def test_full_pipeline_inventory_columns_sampling_describing() -> None:
    from src.services.db_introspection.mongo_inspector import study_mongo_schema
    from src.services.db_introspection.schema_doc import SchemaDocument

    factory, produced = _factory_for(_sample_db())
    resolver, create_mock = _stub_resolver()

    doc = await study_mongo_schema(
        uri="mongodb://svc:hunter2@db.internal:27017/app",
        database="app",
        ai_model_resolver=resolver,
        _client_factory=factory,
    )

    # Strict re-validation of the dumped form.
    SchemaDocument.model_validate(doc.model_dump(mode="json"))

    assert doc.dialect == "mongodb"
    assert doc.agent_version == "studying-agent@0.3"
    assert len(doc.fingerprint) == 64
    assert doc.vector_index_ref is None
    assert doc.study_duration_ms >= 0

    # --- INVENTORY: system.* skipped, two collections discovered + qualified.
    names = {t.name for t in doc.tables}
    assert names == {"app.users", "app.audit_logs"}
    assert all(t.kind == "collection" for t in doc.tables)

    by_short = {t.name.split(".", 1)[1]: t for t in doc.tables}
    users = by_short["users"]
    audit = by_short["audit_logs"]

    # --- COLUMNS: union of top-level keys, types inferred, schema-on-read.
    user_cols = {c.name: c for c in users.columns}
    assert "_id" in user_cols and users.primary_key == ["_id"]
    assert set(user_cols) == {
        "_id", "email", "age", "active", "score", "joined", "tags",
        "profile", "avatar",
    }
    assert user_cols["_id"].type == "uuid"  # ObjectId → uuid
    assert user_cols["email"].type == "text"
    assert user_cols["age"].type == "int"
    assert user_cols["active"].type == "bool"
    assert user_cols["score"].type == "float"
    assert user_cols["joined"].type == "datetime"
    assert user_cols["tags"].type == "array<text>"
    assert user_cols["profile"].type == "object"
    assert user_cols["avatar"].type == "binary"
    # Every Mongo column: inferred + nullable.
    assert all(c.inferred is True for c in users.columns)
    assert all(c.nullable is True for c in users.columns)
    # native_type carries the BSON-ish name.
    assert user_cols["_id"].native_type == "objectId"
    assert user_cols["age"].native_type == "int"
    assert user_cols["avatar"].native_type == "binData"

    # --- SAMPLING: ≤3 distinct redacted values; email redacted + flagged.
    email_col = user_cols["email"]
    assert email_col.is_pii_candidate is True
    assert len(email_col.sample_values) <= 3
    for v in email_col.sample_values:
        assert "@example.com" in v
        assert v.startswith(("a***@", "b***@", "c***@"))
    # BSON binary field is never sampled / stringified.
    assert user_cols["avatar"].sample_values == []
    # Nested object/array fields aren't stringified into sample_values.
    assert user_cols["profile"].sample_values == []
    assert user_cols["tags"].sample_values == []
    # A scalar non-PII field is sampled normally.
    assert user_cols["age"].sample_values
    assert all(v is not None for v in user_cols["age"].sample_values)

    # --- DESCRIBING: one call per collection + one summary.
    assert create_mock.await_count == len(doc.tables) + 1
    assert users.description == "Holds documents for this collection."
    assert "document_store" in users.tags
    # audit_logs gets the heuristic 'audit_log' tag merged in.
    assert "audit_log" in audit.tags
    assert doc.summary == "This database stores users and audit events."

    # --- assembled doc -------------------------------------------------
    assert doc.partial is False
    assert doc.phase_errors == []
    assert [t.name for t in doc.tables] == sorted(t.name for t in doc.tables)
    # No credentials leaked anywhere in the (empty) error list — sanity.
    for e in doc.phase_errors:  # pragma: no cover - empty
        assert "hunter2" not in e.message

    # The motor client was closed.
    assert produced and produced[0].closed is True


async def test_single_collection_filter_restricts_inventory() -> None:
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    factory, _ = _factory_for(_sample_db())

    doc = await study_mongo_schema(
        uri="mongodb://localhost:27017",
        database="app",
        collection_filter="users",
        ai_model_resolver=None,
        _client_factory=factory,
    )
    assert {t.name for t in doc.tables} == {"app.users"}


async def test_per_collection_columns_failure_records_phase_error_and_continues() -> None:
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    db = _FakeDatabase(
        {"users": [{"_id": _FakeObjectId(), "email": "x@y.com"}], "broken": []},
        find_errors={"broken": RuntimeError("find blew up for broken")},
    )
    factory, _ = _factory_for(db)
    resolver, _ = _stub_resolver()

    doc = await study_mongo_schema(
        uri="mongodb://localhost:27017",
        database="app",
        ai_model_resolver=resolver,
        _client_factory=factory,
    )

    assert doc.partial is True
    phases = {e.phase for e in doc.phase_errors}
    keys = {e.error_key for e in doc.phase_errors}
    assert "COLUMNS" in phases
    assert "SAMPLE_DOCS_FAILED" in keys
    # 'broken' dropped; 'users' survived.
    remaining = {t.name.split(".", 1)[1] for t in doc.tables}
    assert "users" in remaining
    assert "broken" not in remaining
    # No PII leaked into the error.
    for e in doc.phase_errors:
        assert "x@y.com" not in e.message


async def test_per_collection_sampling_failure_keeps_columns_and_marks_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.db_introspection import mongo_inspector as mi
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    factory, _ = _factory_for(_sample_db())
    resolver, _ = _stub_resolver()

    def _boom(_columns: Any, _docs: Any) -> None:
        raise RuntimeError("sampling derivation blew up")

    monkeypatch.setattr(mi, "_fill_samples_from_docs", _boom)

    doc = await study_mongo_schema(
        uri="mongodb://localhost:27017",
        database="app",
        ai_model_resolver=resolver,
        _client_factory=factory,
    )

    assert doc.partial is True
    sampling_errors = [e for e in doc.phase_errors if e.phase == "SAMPLING"]
    assert sampling_errors and sampling_errors[0].error_key == "SAMPLE_FAILED"
    # Columns survive a sampling failure; sample_values just stay empty.
    by_short = {t.name.split(".", 1)[1]: t for t in doc.tables}
    assert by_short["users"].columns
    assert all(not c.sample_values for c in by_short["users"].columns)


async def test_no_resolver_skips_describing_and_marks_partial() -> None:
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    factory, _ = _factory_for(_sample_db())

    doc = await study_mongo_schema(
        uri="mongodb://localhost:27017",
        database="app",
        ai_model_resolver=None,
        _client_factory=factory,
    )

    assert doc.partial is True
    assert any(e.error_key == "LLM_UNAVAILABLE" for e in doc.phase_errors)
    assert doc.summary == ""
    # Heuristic tags still applied.
    assert all(isinstance(t.tags, list) and t.tags for t in doc.tables)


async def test_no_collections_raises_phase_error() -> None:
    from src.services.db_introspection import SchemaStudyPhaseError
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    factory, _ = _factory_for(_FakeDatabase({"system.indexes": []}))
    with pytest.raises(SchemaStudyPhaseError) as excinfo:
        await study_mongo_schema(
            uri="mongodb://localhost:27017",
            database="app",
            ai_model_resolver=None,
            _client_factory=factory,
        )
    assert excinfo.value.phase == "INVENTORY"
    assert excinfo.value.error_key == "NO_COLLECTIONS"


async def test_ping_failure_raises_connecting_phase_error() -> None:
    from src.services.db_introspection import SchemaStudyPhaseError
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    db = _FakeDatabase(
        {"users": []}, ping_error=RuntimeError("connection refused to db.internal:27017")
    )
    factory, produced = _factory_for(db)
    with pytest.raises(SchemaStudyPhaseError) as excinfo:
        await study_mongo_schema(
            uri="mongodb://svc:pw@db.internal:27017/app",
            database="app",
            ai_model_resolver=None,
            _client_factory=factory,
        )
    assert excinfo.value.phase == "CONNECT"
    assert excinfo.value.error_key == "CONNECT_REFUSED"
    # Sanitised — no host:port / credentials in the message.
    assert "db.internal" not in excinfo.value.message
    assert "27017" not in excinfo.value.message
    # Client still closed on the way out.
    assert produced and produced[0].closed is True


async def test_motor_driver_missing_raises_clean_phase_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.db_introspection import SchemaStudyPhaseError
    from src.services.db_introspection import mongo_inspector as mi
    from src.services.db_introspection.mongo_inspector import study_mongo_schema

    def _raise() -> Any:
        raise mi.SchemaStudyPhaseError(
            phase="CONNECTING",
            error_key="MONGO_DRIVER_MISSING",
            message="The MongoDB driver (motor/pymongo) is not installed.",
        )

    # Simulate "motor not importable" by making the lazy importer raise.
    monkeypatch.setattr(mi, "_import_motor_client", _raise)

    with pytest.raises(SchemaStudyPhaseError) as excinfo:
        await study_mongo_schema(
            uri="mongodb://localhost:27017",
            database="app",
            ai_model_resolver=None,
        )
    assert excinfo.value.phase == "CONNECT"
    assert excinfo.value.error_key == "MONGO_DRIVER_MISSING"


# ---------------------------------------------------------------------------
# Tests — type-inference helpers (the bits real-Mongo behaviour leans on)
# ---------------------------------------------------------------------------


def test_infer_type_scalars_and_arrays() -> None:
    from src.services.db_introspection.mongo_inspector import _infer_type

    assert _infer_type(True) == "bool"
    assert _infer_type(7) == "int"
    assert _infer_type(3.14) == "float"
    assert _infer_type("hi") == "text"
    assert _infer_type({"a": 1}) == "object"
    assert _infer_type([1, 2, 3]) == "array<int>"
    assert _infer_type(["a"]) == "array<text>"
    assert _infer_type([]) == "array<unknown>"
    assert _infer_type(datetime(2024, 1, 1)) == "datetime"
    assert _infer_type(_FakeObjectId()) == "uuid"
    assert _infer_type(_FakeBinary(b"\x00")) == "binary"
    assert _infer_type(object()) == "unknown"


def test_coalesce_field_type_handles_mixed_and_missing() -> None:
    from src.services.db_introspection.mongo_inspector import _coalesce_field_type

    assert _coalesce_field_type([1, 2, 3]) == "int"
    assert _coalesce_field_type([1, None, 2]) == "int"  # None ignored
    assert _coalesce_field_type([]) == "unknown"
    assert _coalesce_field_type([None, None]) == "unknown"
    assert _coalesce_field_type([1, "x"]) == "unknown"  # disagreement
    assert _coalesce_field_type([[1], ["x"]]) == "array<unknown>"  # all arrays


async def test_mongodb_connector_study_schema_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    """``DatabaseConnector(mongodb).study_schema()`` → MongoDBConnector → inspector."""
    from src.connectors.database_connector import DatabaseConnector
    from src.services.db_introspection import mongo_inspector as mi

    captured: dict[str, Any] = {}

    async def _fake_study(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return MagicMock(name="SchemaDocument")

    monkeypatch.setattr(mi, "study_mongo_schema", _fake_study)
    # Also avoid touching the DI container for the resolver.
    from src.connectors.mongodb_connector import MongoDBConnector

    monkeypatch.setattr(MongoDBConnector, "_resolve_ai_model_resolver", staticmethod(lambda: None))

    conn = DatabaseConnector(
        config={
            "db_type": "mongodb",
            "uri": "mongodb://localhost:27017",
            "database": "app",
            "collection": "users",
        }
    )
    await conn.study_schema()
    assert captured["uri"] == "mongodb://localhost:27017"
    assert captured["database"] == "app"
    assert captured["collection_filter"] == "users"
