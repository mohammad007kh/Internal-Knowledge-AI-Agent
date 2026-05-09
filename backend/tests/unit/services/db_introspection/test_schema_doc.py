"""Unit tests for the SchemaDocument Pydantic contract + fingerprint helper.

These tests must pass without a database — they exercise pure-Python
behaviour: validation, strict-mode rejection, JSON round-tripping and
fingerprint stability.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.services.db_introspection import (
    ColumnDoc,
    IndexDoc,
    PhaseError,
    Relationship,
    SchemaDocument,
    TableDoc,
    compute_fingerprint,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _users_table() -> TableDoc:
    return TableDoc(
        name="public.users",
        kind="table",
        row_count_estimate=120,
        primary_key=["id"],
        indexes=[IndexDoc(name="users_pkey", columns=["id"], unique=True)],
        columns=[
            ColumnDoc(
                name="id",
                type="uuid",
                native_type="uuid",
                nullable=False,
                default=None,
                sample_values=[],
                is_pii_candidate=False,
                inferred=False,
            ),
            ColumnDoc(
                name="email",
                type="text",
                native_type="varchar(254)",
                nullable=False,
                default=None,
                sample_values=["alice@example.com"],
                is_pii_candidate=True,
                inferred=False,
            ),
        ],
        relationships=[],
        description="Stores account credentials.",
        tags=["transactional"],
    )


def _orders_table() -> TableDoc:
    return TableDoc(
        name="public.orders",
        kind="table",
        primary_key=["id"],
        columns=[
            ColumnDoc(
                name="id",
                type="uuid",
                native_type="uuid",
                nullable=False,
            ),
            ColumnDoc(
                name="user_id",
                type="uuid",
                native_type="uuid",
                nullable=False,
            ),
            ColumnDoc(
                name="amount_cents",
                type="int",
                native_type="bigint",
                nullable=False,
            ),
        ],
        relationships=[
            Relationship(
                from_columns=["user_id"],
                to_table="public.users",
                to_columns=["id"],
                kind="foreign_key",
            )
        ],
    )


def _build_doc(*, fingerprint: str = "0" * 64) -> SchemaDocument:
    return SchemaDocument(
        dialect="postgresql",
        fingerprint=fingerprint,
        generated_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        agent_version="1.0.0",
        study_duration_ms=1234,
        partial=False,
        phase_errors=[],
        tables=[_users_table(), _orders_table()],
        summary="Two-table OLTP store: users + orders.",
        vector_index_ref=None,
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestSchemaDocumentRoundTrip:
    def test_construct_minimal_document(self) -> None:
        doc = _build_doc()
        assert doc.dialect == "postgresql"
        assert len(doc.tables) == 2

    def test_json_round_trip_is_lossless(self) -> None:
        original = _build_doc()
        as_json = original.model_dump_json()
        rebuilt = SchemaDocument.model_validate_json(as_json)
        assert rebuilt == original

    def test_dict_round_trip_is_lossless(self) -> None:
        original = _build_doc()
        rebuilt = SchemaDocument.model_validate(original.model_dump(mode="json"))
        assert rebuilt == original

    def test_vector_index_ref_defaults_to_none(self) -> None:
        doc = _build_doc()
        assert doc.vector_index_ref is None


# ---------------------------------------------------------------------------
# Strict mode — extra="forbid" everywhere
# ---------------------------------------------------------------------------


class TestStrictModeForbidsExtraFields:
    def test_top_level_extra_field_rejected(self) -> None:
        payload = _build_doc().model_dump(mode="json")
        payload["unknown_field"] = "boom"
        with pytest.raises(ValidationError):
            SchemaDocument.model_validate(payload)

    def test_table_extra_field_rejected(self) -> None:
        payload = _build_doc().model_dump(mode="json")
        payload["tables"][0]["unexpected"] = "x"
        with pytest.raises(ValidationError):
            SchemaDocument.model_validate(payload)

    def test_column_extra_field_rejected(self) -> None:
        payload = _build_doc().model_dump(mode="json")
        payload["tables"][0]["columns"][0]["surprise"] = "x"
        with pytest.raises(ValidationError):
            SchemaDocument.model_validate(payload)

    def test_index_extra_field_rejected(self) -> None:
        payload = _build_doc().model_dump(mode="json")
        payload["tables"][0]["indexes"][0]["bogus"] = "x"
        with pytest.raises(ValidationError):
            SchemaDocument.model_validate(payload)

    def test_relationship_extra_field_rejected(self) -> None:
        payload = _build_doc().model_dump(mode="json")
        payload["tables"][1]["relationships"][0]["weird"] = "x"
        with pytest.raises(ValidationError):
            SchemaDocument.model_validate(payload)

    def test_phase_error_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PhaseError(  # type: ignore[call-arg]
                phase="SAMPLING",
                error_key="X",
                message="msg",
                extra="boom",
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSchemaDocumentValidation:
    def test_invalid_dialect_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SchemaDocument(  # type: ignore[arg-type]
                dialect="oracle",
                fingerprint="x",
                generated_at=datetime.now(UTC),
                agent_version="1.0.0",
                study_duration_ms=0,
                tables=[],
                summary="",
            )

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SchemaDocument(
                dialect="postgresql",
                fingerprint="x",
                generated_at=datetime.now(UTC),
                agent_version="1.0.0",
                study_duration_ms=-1,
                tables=[],
                summary="",
            )

    def test_invalid_table_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TableDoc(  # type: ignore[arg-type]
                name="x.y",
                kind="not_a_table",
            )

    def test_invalid_relationship_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Relationship(  # type: ignore[arg-type]
                from_columns=["a"],
                to_table="x.y",
                to_columns=["b"],
                kind="bogus",
            )

    def test_array_type_string_accepted_for_column(self) -> None:
        col = ColumnDoc(
            name="tags",
            type="array<text>",
            native_type="text[]",
        )
        assert col.type == "array<text>"

    def test_phase_errors_default_empty(self) -> None:
        doc = _build_doc()
        assert doc.phase_errors == []


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    def test_returns_64_char_hex(self) -> None:
        digest = compute_fingerprint(_build_doc())
        assert len(digest) == 64
        int(digest, 16)  # must parse as hex

    def test_stable_for_identical_input(self) -> None:
        a = compute_fingerprint(_build_doc())
        b = compute_fingerprint(_build_doc())
        assert a == b

    def test_stable_when_tables_reordered(self) -> None:
        original = _build_doc()
        reordered = _build_doc()
        reordered.tables = list(reversed(reordered.tables))
        assert compute_fingerprint(original) == compute_fingerprint(reordered)

    def test_stable_when_columns_reordered(self) -> None:
        original = _build_doc()
        reordered = _build_doc()
        reordered.tables[0].columns = list(reversed(reordered.tables[0].columns))
        assert compute_fingerprint(original) == compute_fingerprint(reordered)

    def test_stable_when_descriptions_change(self) -> None:
        """Descriptions are LLM noise — they MUST NOT change the fingerprint."""
        original = _build_doc()
        modified = _build_doc()
        modified.tables[0].description = "Completely different prose."
        modified.summary = "A totally new summary."
        assert compute_fingerprint(original) == compute_fingerprint(modified)

    def test_stable_when_sample_values_change(self) -> None:
        original = _build_doc()
        modified = _build_doc()
        modified.tables[0].columns[1].sample_values = ["bob@example.com"]
        assert compute_fingerprint(original) == compute_fingerprint(modified)

    def test_sensitive_to_column_name_change(self) -> None:
        original = _build_doc()
        renamed = _build_doc()
        renamed.tables[0].columns[1] = ColumnDoc(
            name="email_address",  # renamed
            type="text",
            native_type="varchar(254)",
            nullable=False,
        )
        assert compute_fingerprint(original) != compute_fingerprint(renamed)

    def test_sensitive_to_column_type_change(self) -> None:
        original = _build_doc()
        retyped = _build_doc()
        retyped.tables[0].columns[1] = ColumnDoc(
            name="email",
            type="json",  # was 'text'
            native_type="jsonb",
            nullable=False,
        )
        assert compute_fingerprint(original) != compute_fingerprint(retyped)

    def test_sensitive_to_added_column(self) -> None:
        original = _build_doc()
        plus_one = _build_doc()
        plus_one.tables[0].columns.append(
            ColumnDoc(name="created_at", type="datetime", native_type="timestamptz")
        )
        assert compute_fingerprint(original) != compute_fingerprint(plus_one)

    def test_sensitive_to_removed_table(self) -> None:
        original = _build_doc()
        minus_one = _build_doc()
        minus_one.tables = minus_one.tables[:1]
        assert compute_fingerprint(original) != compute_fingerprint(minus_one)

    def test_normalises_type_casing(self) -> None:
        original = _build_doc()
        upper = _build_doc()
        upper.tables[0].columns[0] = ColumnDoc(
            name="id",
            type="UUID",  # casing variance
            native_type="uuid",
            nullable=False,
        )
        # type literal isn't 'UUID' (literal is 'uuid'), but the field
        # accepts open-ended strings — and the fingerprint MUST normalise.
        assert compute_fingerprint(original) == compute_fingerprint(upper)
