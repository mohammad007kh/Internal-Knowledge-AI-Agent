"""DB-source studying-agent public surface.

Phase 1 shipped the data contract + persistence. The SQL-dialect inspector
(the real 6-phase pipeline for postgresql / mysql / mssql) lands here.
MongoDB introspection and the vector-index (INDEXING) phase are still
follow-ups.
"""

from src.services.db_introspection._errors import (
    SchemaStudyPhaseError,
    failed_state_prefix,
)
from src.services.db_introspection.fingerprint import compute_fingerprint
from src.services.db_introspection.pii_redaction import (
    column_name_looks_pii,
    looks_pii,
    redact_value,
    value_looks_pii,
)
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    IndexDoc,
    PhaseError,
    Relationship,
    SchemaDocument,
    TableDoc,
)
from src.services.db_introspection.sql_inspector import (
    AGENT_VERSION,
    study_sql_schema,
)

__all__ = [
    "AGENT_VERSION",
    "ColumnDoc",
    "IndexDoc",
    "PhaseError",
    "Relationship",
    "SchemaDocument",
    "SchemaStudyPhaseError",
    "TableDoc",
    "column_name_looks_pii",
    "compute_fingerprint",
    "failed_state_prefix",
    "looks_pii",
    "redact_value",
    "study_sql_schema",
    "value_looks_pii",
]
