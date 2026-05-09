"""DB-source studying-agent — Phase 1 public surface.

Phase 1 ships only the data contract and persistence primitives.
Inspectors, the orchestrator and the API surface are added in later phases.
"""

from src.services.db_introspection.fingerprint import compute_fingerprint
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    IndexDoc,
    PhaseError,
    Relationship,
    SchemaDocument,
    TableDoc,
)

__all__ = [
    "ColumnDoc",
    "IndexDoc",
    "PhaseError",
    "Relationship",
    "SchemaDocument",
    "TableDoc",
    "compute_fingerprint",
]
