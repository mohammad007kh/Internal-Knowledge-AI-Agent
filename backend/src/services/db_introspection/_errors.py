"""Phase-aware exception for the studying-agent pipeline.

The studying-agent's six phases (CONNECTING / INVENTORY / COLUMNS /
SAMPLING / DESCRIBING / INDEXING) each have an associated terminal study
state — ``CONNECT_FAILED``, ``INVENTORY_FAILED`` etc. When an inspector
hits a *fatal* error (one that aborts the whole study, as opposed to a
per-table degradation recorded as a :class:`~src.services.db_introspection.schema_doc.PhaseError`)
it raises :class:`SchemaStudyPhaseError` so the orchestrator can stamp the
correct ``<phase>_FAILED`` state without having to guess the phase from
the exception type or parse its message.

The orchestrator (:mod:`src.tasks.study_source`) checks for this type
first in its ``_phase_from_exception`` helper; any other exception falls
back to the legacy heuristic (ConnectionError → CONNECT, else INVENTORY).

``message`` is always pre-sanitised by the raiser — it MUST NOT contain a
connection string, credentials, or PII.  ``phase`` here is the *failed
state prefix* (``CONNECT``, ``INVENTORY``, ``COLUMNS``, ``SAMPLING``,
``DESCRIBING``, ``INDEXING``) — i.e. what gets suffixed with ``_FAILED``,
not the in-flight phase name (which uses ``CONNECTING``).
"""

from __future__ import annotations

from typing import Final

#: Map a pipeline-phase name (as used in :data:`schema_doc.PhaseLiteral`)
#: to the failed-state prefix the orchestrator stamps via ``mark_failed``.
#: ``CONNECTING`` → ``CONNECT_FAILED``; every other phase keeps its name.
_PHASE_TO_FAILED_PREFIX: Final[dict[str, str]] = {
    "CONNECTING": "CONNECT",
    "INVENTORY": "INVENTORY",
    "COLUMNS": "COLUMNS",
    "SAMPLING": "SAMPLING",
    "DESCRIBING": "DESCRIBING",
    "INDEXING": "INDEXING",
}


def failed_state_prefix(phase: str) -> str:
    """Return the ``<PREFIX>_FAILED`` prefix for *phase*.

    Unknown phases fall through to ``INVENTORY`` — the safest default for
    "something went wrong early".
    """
    return _PHASE_TO_FAILED_PREFIX.get(phase.upper(), "INVENTORY")


class SchemaStudyPhaseError(Exception):
    """A fatal failure during one studying-agent phase.

    Attributes
    ----------
    phase:
        The failed-state prefix (``CONNECT`` / ``INVENTORY`` / ``COLUMNS``
        / ``SAMPLING`` / ``DESCRIBING`` / ``INDEXING``).  Pass either the
        in-flight phase name (``CONNECTING``) or the prefix directly — the
        constructor normalises ``CONNECTING`` → ``CONNECT``.
    error_key:
        Stable machine-readable key, e.g. ``CONNECT_TIMEOUT`` or
        ``SAMPLE_DENIED``.  Used for retry routing / admin filters.
    message:
        Admin-readable text.  MUST already be sanitised by the caller —
        no connection strings, no credentials, no PII.
    """

    def __init__(self, *, phase: str, error_key: str, message: str) -> None:
        self.phase: str = failed_state_prefix(phase)
        self.error_key: str = error_key
        self.message: str = message
        super().__init__(message)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SchemaStudyPhaseError(phase={self.phase!r}, "
            f"error_key={self.error_key!r})"
        )
