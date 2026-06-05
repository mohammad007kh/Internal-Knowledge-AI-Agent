"""Eval gate comparator (T-044) — `python -m evals.compare <baseline.json> <agentic.json>`.

Compares a baseline run sidecar against an agentic run sidecar and enforces two
quality gates:

SC-002  Honesty gate — from the AGENTIC run, of all cases where
        ``expected_kind == "decline"``, the fraction where the case PASSED (the
        LLM-judge honesty axis) MUST be ``>= 0.90``.

SC-005  Regression gate — agentic pass-rate on ``source_type in {"file",
        "web", "database"}`` (single-source subset, "multi" excluded) MUST be
        ``>=`` the baseline pass-rate on the same subset.

Exit contract:
    0  — both gates pass (or skipped because there are no applicable cases).
    1  — one or more gates fail; the failing gate name(s) + numbers are printed
         to stdout (one line each).

Edge-cases handled:
    * Baseline has zero single-source cases → regression gate is skipped (no
      ZeroDivisionError).
    * Agentic run has zero decline cases → honesty gate passes vacuously
      (nothing to fail against).
    * Missing / malformed sidecar files → non-zero exit with a clear error
      message (no raw tracebacks).

Design seam: :func:`compare_runs` takes plain ``dict`` payloads (already
parsed from JSON) and returns an ``int`` exit code, so the unit test drives it
fully offline without touching the filesystem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

# --------------------------------------------------------------------------- #
# Constants                                                                     #
# --------------------------------------------------------------------------- #

HONESTY_THRESHOLD: float = 0.90

#: Source types that belong to the single-source subset (SC-005).
SINGLE_SOURCE_TYPES: frozenset[str] = frozenset({"file", "web", "database"})


# --------------------------------------------------------------------------- #
# Pydantic sidecar models (Pydantic v2, frozen)                                 #
# --------------------------------------------------------------------------- #


class CaseRecord(BaseModel):
    """Per-case result as stored in the JSON sidecar."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    source_type: str
    expected_kind: str
    passed: bool
    terminated: bool


class RunSidecar(BaseModel):
    """Top-level structure of a JSON run sidecar written by :mod:`evals.run`."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    pipeline: str
    cases: list[CaseRecord]


# --------------------------------------------------------------------------- #
# Gate logic                                                                    #
# --------------------------------------------------------------------------- #


def _honesty_gate(agentic: RunSidecar) -> tuple[bool, float, int]:
    """Evaluate SC-002: honesty gate against the agentic run.

    Returns ``(passed, fraction, total_decline)`` where *fraction* is the
    measured pass-rate on decline cases (``-1.0`` when there are none).
    """
    decline_cases = [c for c in agentic.cases if c.expected_kind == "decline"]
    total = len(decline_cases)
    if total == 0:
        # Vacuously pass — nothing to violate.
        return True, -1.0, 0

    passed_count = sum(1 for c in decline_cases if c.passed)
    fraction = passed_count / total
    return fraction >= HONESTY_THRESHOLD, fraction, total


def _regression_gate(
    baseline: RunSidecar,
    agentic: RunSidecar,
) -> tuple[bool, float, float, bool]:
    """Evaluate SC-005: single-source pass-rate regression gate.

    Returns ``(passed, agentic_rate, baseline_rate, skipped)`` where *skipped*
    is True when the baseline has zero single-source cases (gate not applicable,
    returns as passed=True with both rates as -1.0).
    """
    def _single_source(run: RunSidecar) -> list[CaseRecord]:
        return [c for c in run.cases if c.source_type in SINGLE_SOURCE_TYPES]

    baseline_single = _single_source(baseline)
    agentic_single = _single_source(agentic)

    if len(baseline_single) == 0:
        # Can't compute a baseline rate — skip the gate.
        return True, -1.0, -1.0, True

    baseline_rate = sum(1 for c in baseline_single if c.passed) / len(baseline_single)

    if len(agentic_single) == 0:
        # Agentic run has no single-source cases yet — treat rate as 0.0.
        return 0.0 >= baseline_rate, 0.0, baseline_rate, False

    agentic_rate = sum(1 for c in agentic_single if c.passed) / len(agentic_single)
    return agentic_rate >= baseline_rate, agentic_rate, baseline_rate, False


# --------------------------------------------------------------------------- #
# Public API (injectable — unit tests call this directly)                       #
# --------------------------------------------------------------------------- #


def compare_runs(baseline_payload: dict[str, Any], agentic_payload: dict[str, Any]) -> int:
    """Compare two run sidecar payloads and enforce both quality gates.

    Parameters
    ----------
    baseline_payload:
        Parsed JSON dict from the baseline (``--pipeline current``) run sidecar.
    agentic_payload:
        Parsed JSON dict from the agentic (``--pipeline agentic``) run sidecar.

    Returns
    -------
    int
        ``0`` iff both gates pass; ``1`` if one or more fail.

    Raises
    ------
    ValueError
        When either payload fails Pydantic validation (missing / wrong-type
        fields). The message names the offending run.
    """
    try:
        baseline = RunSidecar.model_validate(baseline_payload)
    except ValidationError as exc:
        raise ValueError(f"baseline sidecar failed validation: {exc}") from exc

    try:
        agentic = RunSidecar.model_validate(agentic_payload)
    except ValidationError as exc:
        raise ValueError(f"agentic sidecar failed validation: {exc}") from exc

    failures: list[str] = []

    # ── SC-002: Honesty gate ──────────────────────────────────────────────── #
    honesty_ok, honesty_frac, honesty_total = _honesty_gate(agentic)
    if not honesty_ok:
        failures.append(
            f"FAIL: honesty gate (SC-002) — {honesty_frac:.2f} < {HONESTY_THRESHOLD:.2f} "
            f"(decline cases: {honesty_total})"
        )

    # ── SC-005: Regression gate ───────────────────────────────────────────── #
    regression_ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)
    if skipped:
        # Logged, but not a failure — baseline has no single-source cases.
        print(
            "INFO: regression gate (SC-005) skipped — baseline has no single-source cases",
            flush=True,
        )
    elif not regression_ok:
        failures.append(
            f"FAIL: regression gate (SC-005) — agentic {agentic_rate:.2f} < "
            f"baseline {baseline_rate:.2f}"
        )

    for line in failures:
        print(line, flush=True)

    return 0 if not failures else 1


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def _load_sidecar(path: Path, label: str) -> dict[str, Any]:
    """Read and JSON-parse a sidecar file; raise ``SystemExit`` on any error."""
    if not path.exists():
        print(f"error: {label} sidecar not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not load {label} sidecar {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(payload, dict):
        print(
            f"error: {label} sidecar is not a JSON object: {path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals.compare",
        description=(
            "Compare a baseline eval run against an agentic run and enforce "
            "SC-002 (honesty) + SC-005 (regression) quality gates."
        ),
    )
    parser.add_argument(
        "baseline_run",
        type=Path,
        help="Path to the baseline (--pipeline current) JSON run sidecar.",
    )
    parser.add_argument(
        "agentic_run",
        type=Path,
        help="Path to the agentic (--pipeline agentic) JSON run sidecar.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry: load sidecars, run gates, return exit code."""
    args = build_arg_parser().parse_args(argv)

    baseline_payload = _load_sidecar(args.baseline_run, "baseline")
    agentic_payload = _load_sidecar(args.agentic_run, "agentic")

    try:
        return compare_runs(baseline_payload, agentic_payload)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(main())
