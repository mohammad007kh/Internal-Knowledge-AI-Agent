"""Deterministic SchemaDocument fingerprint.

The fingerprint is the load-bearing primitive for drift detection: two
:class:`SchemaDocument` instances that describe the *same shape* must
produce the same digest regardless of:

* the order of tables / columns / indexes inside the document,
* the ``description``, ``summary``, ``sample_values`` or any narrative
  fields (those are LLM noise, not structural truth),
* the timestamps or agent metadata.

The canonical form is a JSON-serialised, lexicographically-sorted list
of ``(table_name, column_name, normalized_type)`` triples.

Algorithm:

1. Walk every ``TableDoc`` and every ``ColumnDoc`` inside it.
2. Emit ``[table.name, column.name, _normalize_type(column.type)]``.
3. Sort the resulting list lexicographically (Python tuple ordering).
4. ``json.dumps`` with ``sort_keys=True`` and tight separators.
5. sha256 hex digest of the UTF-8 bytes.

Importantly, this function does NOT consult the document's existing
``fingerprint`` field — that field is the *output* and would create a
fixed-point cycle if read back in.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.db_introspection.schema_doc import SchemaDocument


def _normalize_type(raw: str) -> str:
    """Lowercase + strip a column type so casing variance doesn't break drift."""
    return raw.strip().lower()


def compute_fingerprint(doc: SchemaDocument) -> str:
    """Return the canonical sha256 hex digest for *doc*.

    Stable for any reordering of tables / columns; sensitive to:

    * adding or removing a table,
    * adding or removing a column,
    * renaming a table or column,
    * a normalised-type change on any column.
    """
    triples: list[tuple[str, str, str]] = []
    for table in doc.tables:
        for column in table.columns:
            triples.append(
                (
                    table.name,
                    column.name,
                    _normalize_type(str(column.type)),
                )
            )
    triples.sort()
    payload = json.dumps(triples, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
