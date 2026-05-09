"""Strict Pydantic v2 contract for the DB-source studying-agent.

Phase 1 — Deliverable #1.

Every inspector in the studying-agent pipeline (the Mongo, Postgres, MySQL,
MSSQL workers) emits *exactly* this shape.  Strict mode (``extra="forbid"``)
is applied at every level so that any inspector returning extra/unexpected
fields fails loudly at the type boundary instead of silently corrupting
the persisted ``schema_document_json`` blob.

The companion helper :func:`src.services.db_introspection.fingerprint.compute_fingerprint`
is the only blessed way to produce a SchemaDocument fingerprint — see that
module for the canonicalisation algorithm.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

DialectLiteral = Literal["postgresql", "mysql", "mssql", "mongodb"]
"""Supported source dialects for Phase 1."""

TableKindLiteral = Literal["table", "view", "materialized_view", "collection"]
"""Distinct relation flavours we surface."""

RelationshipKindLiteral = Literal["foreign_key", "embedded_hint"]
"""Foreign keys are SQL-native; ``embedded_hint`` is for Mongo nesting."""

PhaseLiteral = Literal[
    "CONNECTING",
    "INVENTORY",
    "COLUMNS",
    "SAMPLING",
    "DESCRIBING",
    "INDEXING",
]
"""Pipeline phases, ordered."""

# Open-ended: literal core types plus arbitrary ``array<T>`` strings.
ColumnTypeLiteral = Literal[
    "text",
    "int",
    "float",
    "bool",
    "date",
    "datetime",
    "json",
    "binary",
    "uuid",
    "enum",
    "object",
    "unknown",
]
"""Normalised column types.  Inspectors may also emit ``array<T>`` strings,
which is why the field is typed ``ColumnTypeLiteral | str`` on
:class:`ColumnDoc`.  Anything outside this enum (other than ``array<T>``)
is a contract violation that callers should reject upstream."""


# ---------------------------------------------------------------------------
# Strict base
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """All studying-agent payload models forbid extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=False)


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------


class PhaseError(_StrictModel):
    """One phase-level failure recorded during a partial study."""

    phase: str = Field(..., description="Phase identifier, e.g. 'SAMPLING'.")
    error_key: str = Field(
        ...,
        description=(
            "Stable machine-readable key, e.g. 'CONNECT_TIMEOUT' or "
            "'SAMPLE_TIMEOUT'.  Used by the orchestrator for retry routing."
        ),
    )
    message: str = Field(
        ...,
        description=(
            "Admin-readable explanation.  MUST NOT include connection strings, "
            "credentials, or PII."
        ),
    )


class IndexDoc(_StrictModel):
    """A single index on a table / collection."""

    name: str
    columns: list[str] = Field(default_factory=list)
    unique: bool = False


class Relationship(_StrictModel):
    """Inferred or declared edge between two relations."""

    from_columns: list[str] = Field(default_factory=list)
    to_table: str
    to_columns: list[str] = Field(default_factory=list)
    kind: RelationshipKindLiteral


class ColumnDoc(_StrictModel):
    """A single column / field within a relation."""

    name: str
    # Literals plus open-ended ``array<T>`` strings — see ColumnTypeLiteral docs.
    type: ColumnTypeLiteral | str
    native_type: str = Field(
        ...,
        description="Raw vendor type string (audit-only, never shown to LLM).",
    )
    nullable: bool = True
    default: str | None = None
    sample_values: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 3 distinct values, PII-redacted at the inspector layer.  "
            "This model holds them verbatim — redaction is the inspector's "
            "responsibility."
        ),
    )
    is_pii_candidate: bool = False
    inferred: bool = Field(
        default=False,
        description="True for Mongo (schema-on-read); False for SQL.",
    )


class TableDoc(_StrictModel):
    """A single relation (table / view / collection)."""

    name: str = Field(
        ...,
        description=(
            "Fully qualified name: 'schema.table' for SQL, "
            "'database.collection' for Mongo."
        ),
    )
    kind: TableKindLiteral
    row_count_estimate: int | None = None
    primary_key: list[str] = Field(
        default_factory=list,
        description="Empty for Mongo unless an explicit '_id' is present.",
    )
    indexes: list[IndexDoc] = Field(default_factory=list)
    columns: list[ColumnDoc] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    description: str = Field(
        default="",
        description="LLM 2-3 sentence summary; empty before DESCRIBING phase.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Heuristic tags such as 'audit_log', 'lookup', 'transactional'.  "
            "Free-form to allow new heuristics without migrations."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class SchemaDocument(_StrictModel):
    """The studying-agent's single source of truth for one source's schema.

    Persisted as JSON in ``schema_studies.schema_document_json`` once the
    pipeline reaches READY or READY_PARTIAL.
    """

    dialect: DialectLiteral
    fingerprint: str = Field(
        ...,
        description=(
            "sha256 hex digest of the canonical column triples — see "
            "compute_fingerprint().  Stored alongside the document for "
            "drift detection without re-hashing."
        ),
    )
    generated_at: datetime = Field(
        ...,
        description="UTC timestamp when the document was finalised.",
    )
    agent_version: str = Field(
        ...,
        description="Semver of the studying-agent that produced this document.",
    )
    study_duration_ms: int = Field(
        ...,
        ge=0,
        description="Total wall-clock time across all phases.",
    )
    partial: bool = Field(
        default=False,
        description="True if any phase failed but READY_PARTIAL still emitted.",
    )
    phase_errors: list[PhaseError] = Field(default_factory=list)
    tables: list[TableDoc] = Field(default_factory=list)
    summary: str = Field(
        default="",
        description="Corpus-level LLM summary, 4-6 sentences.",
    )
    vector_index_ref: str | None = Field(
        default=None,
        description=(
            "Phase 1: always None.  Phase 2 will populate with a pointer to "
            "the per-source vector index (e.g. 'schema_doc::<study_id>')."
        ),
    )
