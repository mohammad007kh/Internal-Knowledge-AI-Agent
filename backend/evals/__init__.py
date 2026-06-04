"""Outcome-based eval harness (file-based JSON-golden cases).

This package is intentionally NOT part of ``src`` — eval cases live under
``backend/evals/cases/`` as JSON-golden fixtures (per data-model §5), not in a
DB table. The harness is consumed programmatically by the later eval tasks
(T-041 seed SQL, T-042 runner, T-043 judge, T-044 CI gate).
"""
