"""Unit tests for the eval gate comparator (T-044) — fully offline.

:func:`evals.compare.compare_runs` takes plain ``dict`` payloads (hand-built
Python dicts matching the sidecar schema) so the whole gate logic is exercised
here with NO filesystem I/O, NO LLM, NO DB.

Coverage matrix (from the task):
* Both gates pass → ``compare_runs()`` returns 0.
* Honesty fraction = 0.83 (below 0.90 threshold) → returns 1, stdout names
  the honesty gate.
* Agentic single-source pass-rate below baseline → returns 1, names the
  regression gate.
* Empty sidecar / missing required field → non-zero exit (ValueError raised,
  converted to exit 1 in the ``main()`` path).
* Baseline has no single-source cases → regression gate skipped (no
  ZeroDivisionError).

All strings, IDs, and answers are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.compare import (
    HONESTY_THRESHOLD,
    SINGLE_SOURCE_TYPES,
    RunSidecar,
    _honesty_gate,
    _regression_gate,
    compare_runs,
    main,
)

# --------------------------------------------------------------------------- #
# Sidecar factories (synthetic)                                                 #
# --------------------------------------------------------------------------- #


def _case_record(
    *,
    id: str = "case-01",
    source_type: str = "file",
    expected_kind: str = "answer",
    passed: bool = True,
    terminated: bool = True,
) -> dict[str, Any]:
    """Build a synthetic per-case record dict matching the sidecar schema."""
    return {
        "id": id,
        "source_type": source_type,
        "expected_kind": expected_kind,
        "passed": passed,
        "terminated": terminated,
    }


def _sidecar(
    *,
    pipeline: str = "current",
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a synthetic run sidecar dict."""
    return {
        "pipeline": pipeline,
        "timestamp": "20260606T020000Z",
        "total_cases": len(cases or []),
        "cases": cases or [],
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #


def _parse(payload: dict[str, Any]) -> RunSidecar:
    return RunSidecar.model_validate(payload)


# --------------------------------------------------------------------------- #
# Honesty gate unit tests (_honesty_gate)                                       #
# --------------------------------------------------------------------------- #


def test_honesty_gate_passes_when_fraction_meets_threshold() -> None:
    """9 of 10 decline cases pass → 0.90 >= 0.90 → gate passes."""
    cases = [
        _case_record(id=f"dec-{i:02d}", expected_kind="decline", passed=True)
        for i in range(9)
    ] + [_case_record(id="dec-09", expected_kind="decline", passed=False)]
    sidecar = _parse(_sidecar(pipeline="agentic", cases=cases))
    ok, fraction, total = _honesty_gate(sidecar)

    assert ok is True
    assert fraction == pytest.approx(0.90)
    assert total == 10


def test_honesty_gate_fails_when_fraction_below_threshold() -> None:
    """5 of 6 decline cases pass → 0.83 < 0.90 → gate fails."""
    cases = [
        _case_record(id=f"dec-{i:02d}", expected_kind="decline", passed=True)
        for i in range(5)
    ] + [_case_record(id="dec-05", expected_kind="decline", passed=False)]
    sidecar = _parse(_sidecar(pipeline="agentic", cases=cases))
    ok, fraction, total = _honesty_gate(sidecar)

    assert ok is False
    assert fraction == pytest.approx(5 / 6)
    assert total == 6


def test_honesty_gate_vacuously_passes_with_no_decline_cases() -> None:
    """No decline cases at all → vacuously passes (nothing to fail)."""
    cases = [_case_record(id="ans-01", expected_kind="answer", passed=True)]
    sidecar = _parse(_sidecar(pipeline="agentic", cases=cases))
    ok, fraction, total = _honesty_gate(sidecar)

    assert ok is True
    assert total == 0
    assert fraction == -1.0


def test_honesty_gate_passes_all_decline_passed() -> None:
    """All decline cases pass → 1.0 >= 0.90 → gate passes."""
    cases = [
        _case_record(id=f"dec-{i:02d}", expected_kind="decline", passed=True)
        for i in range(5)
    ]
    sidecar = _parse(_sidecar(pipeline="agentic", cases=cases))
    ok, fraction, total = _honesty_gate(sidecar)

    assert ok is True
    assert fraction == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Regression gate unit tests (_regression_gate)                                 #
# --------------------------------------------------------------------------- #


def test_regression_gate_passes_when_agentic_rate_equals_baseline() -> None:
    """Agentic = baseline single-source rate (1.0 >= 1.0) → passes."""
    baseline = _parse(_sidecar(cases=[_case_record(id="b-01", source_type="file", passed=True)]))
    agentic = _parse(_sidecar(pipeline="agentic", cases=[_case_record(id="a-01", source_type="file", passed=True)]))

    ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)

    assert ok is True
    assert agentic_rate == pytest.approx(1.0)
    assert baseline_rate == pytest.approx(1.0)
    assert skipped is False


def test_regression_gate_fails_when_agentic_rate_below_baseline() -> None:
    """Baseline 1.0, agentic 0.5 on single-source → regression fails."""
    baseline = _parse(
        _sidecar(
            cases=[
                _case_record(id="b-01", source_type="file", passed=True),
                _case_record(id="b-02", source_type="file", passed=True),
            ]
        )
    )
    agentic = _parse(
        _sidecar(
            pipeline="agentic",
            cases=[
                _case_record(id="a-01", source_type="file", passed=True),
                _case_record(id="a-02", source_type="file", passed=False),
            ],
        )
    )

    ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)

    assert ok is False
    assert agentic_rate == pytest.approx(0.5)
    assert baseline_rate == pytest.approx(1.0)
    assert skipped is False


def test_regression_gate_skipped_when_baseline_has_no_single_source_cases() -> None:
    """Baseline only has multi cases → gate is skipped (no ZeroDivisionError)."""
    baseline = _parse(
        _sidecar(
            cases=[
                _case_record(id="m-01", source_type="multi", passed=True),
            ]
        )
    )
    agentic = _parse(
        _sidecar(
            pipeline="agentic",
            cases=[_case_record(id="a-01", source_type="file", passed=False)],
        )
    )

    ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)

    assert ok is True
    assert skipped is True
    assert agentic_rate == -1.0
    assert baseline_rate == -1.0


def test_regression_gate_multi_excluded_from_subset() -> None:
    """``multi`` source_type is excluded from the single-source subset."""
    baseline = _parse(
        _sidecar(
            cases=[
                _case_record(id="b-01", source_type="file", passed=True),
                _case_record(id="b-multi", source_type="multi", passed=True),
            ]
        )
    )
    agentic = _parse(
        _sidecar(
            pipeline="agentic",
            cases=[
                _case_record(id="a-01", source_type="file", passed=True),
                _case_record(id="a-multi", source_type="multi", passed=False),
            ],
        )
    )

    # multi cases on both sides are excluded; only "file" rows count.
    ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)

    assert ok is True
    assert agentic_rate == pytest.approx(1.0)
    assert baseline_rate == pytest.approx(1.0)


def test_regression_gate_all_single_source_types_counted() -> None:
    """file, web, and database all belong to the single-source subset."""
    assert SINGLE_SOURCE_TYPES == {"file", "web", "database"}

    baseline = _parse(
        _sidecar(
            cases=[
                _case_record(id="b-f", source_type="file", passed=True),
                _case_record(id="b-w", source_type="web", passed=True),
                _case_record(id="b-d", source_type="database", passed=True),
            ]
        )
    )
    agentic = _parse(
        _sidecar(
            pipeline="agentic",
            cases=[
                _case_record(id="a-f", source_type="file", passed=True),
                _case_record(id="a-w", source_type="web", passed=True),
                _case_record(id="a-d", source_type="database", passed=False),
            ],
        )
    )

    ok, agentic_rate, baseline_rate, skipped = _regression_gate(baseline, agentic)

    assert ok is False
    assert agentic_rate == pytest.approx(2 / 3)
    assert baseline_rate == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# compare_runs: integration-level gate orchestration                            #
# --------------------------------------------------------------------------- #


def test_compare_runs_returns_0_when_both_gates_pass() -> None:
    """Both gates pass → exit code 0."""
    baseline = _sidecar(
        cases=[_case_record(id="b-01", source_type="file", passed=True)]
    )
    agentic = _sidecar(
        pipeline="agentic",
        cases=[
            _case_record(id="a-01", source_type="file", passed=True),
            _case_record(id="a-dec", source_type="file", expected_kind="decline", passed=True),
        ],
    )

    assert compare_runs(baseline, agentic) == 0


def test_compare_runs_returns_1_when_honesty_gate_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """5 of 6 decline cases pass (0.83 < 0.90) → exit 1, honesty gate named."""
    baseline = _sidecar(cases=[_case_record(id="b-01", source_type="file", passed=True)])
    decline_cases = [
        _case_record(id=f"a-dec-{i:02d}", source_type="file", expected_kind="decline", passed=True)
        for i in range(5)
    ] + [
        _case_record(id="a-dec-05", source_type="file", expected_kind="decline", passed=False)
    ]
    agentic = _sidecar(pipeline="agentic", cases=decline_cases)

    rc = compare_runs(baseline, agentic)
    captured = capsys.readouterr()

    assert rc == 1
    assert "honesty gate" in captured.out
    assert "SC-002" in captured.out
    # The fraction must be surfaced in the output.
    assert "0.83" in captured.out


def test_compare_runs_returns_1_when_regression_gate_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Agentic single-source 0.50 < baseline 1.0 → exit 1, regression gate named."""
    baseline = _sidecar(
        cases=[
            _case_record(id="b-01", source_type="file", passed=True),
            _case_record(id="b-02", source_type="file", passed=True),
        ]
    )
    agentic = _sidecar(
        pipeline="agentic",
        cases=[
            _case_record(id="a-01", source_type="file", passed=True),
            _case_record(id="a-02", source_type="file", passed=False),
        ],
    )

    rc = compare_runs(baseline, agentic)
    captured = capsys.readouterr()

    assert rc == 1
    assert "regression gate" in captured.out
    assert "SC-005" in captured.out


def test_compare_runs_returns_1_when_both_gates_fail(capsys: pytest.CaptureFixture[str]) -> None:
    """Both gates fail → exit 1, both named in stdout."""
    # Baseline passes 100% on single-source.
    baseline = _sidecar(
        cases=[_case_record(id="b-01", source_type="file", passed=True)]
    )
    # Agentic: single-source all fail (regression), decline 0% pass (honesty).
    agentic = _sidecar(
        pipeline="agentic",
        cases=[
            _case_record(id="a-01", source_type="file", passed=False),
            _case_record(id="a-dec-01", source_type="file", expected_kind="decline", passed=False),
        ],
    )

    rc = compare_runs(baseline, agentic)
    captured = capsys.readouterr()

    assert rc == 1
    assert "honesty gate" in captured.out
    assert "regression gate" in captured.out


def test_compare_runs_skips_regression_gate_when_baseline_has_no_single_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Baseline has only multi cases → regression gate skipped, no ZeroDivisionError."""
    baseline = _sidecar(
        cases=[_case_record(id="m-01", source_type="multi", passed=True)]
    )
    agentic = _sidecar(
        pipeline="agentic",
        cases=[_case_record(id="a-01", source_type="file", passed=False)],
    )

    rc = compare_runs(baseline, agentic)
    captured = capsys.readouterr()

    assert rc == 0
    assert "skipped" in captured.out.lower()


def test_compare_runs_raises_value_error_on_missing_required_field() -> None:
    """A sidecar missing the required 'cases' field raises ValueError."""
    bad_baseline: dict[str, Any] = {"pipeline": "current"}  # missing 'cases'
    good_agentic = _sidecar(pipeline="agentic", cases=[])

    with pytest.raises(ValueError, match="baseline sidecar failed validation"):
        compare_runs(bad_baseline, good_agentic)


def test_compare_runs_raises_value_error_on_bad_agentic_sidecar() -> None:
    """A malformed agentic sidecar (wrong type for 'cases') raises ValueError."""
    good_baseline = _sidecar(cases=[])
    bad_agentic: dict[str, Any] = {"pipeline": "agentic", "cases": "not-a-list"}

    with pytest.raises(ValueError, match="agentic sidecar failed validation"):
        compare_runs(good_baseline, bad_agentic)


def test_compare_runs_empty_sidecars_both_pass() -> None:
    """Both sidecars have zero cases → both gates pass vacuously, exit 0."""
    assert compare_runs(_sidecar(cases=[]), _sidecar(pipeline="agentic", cases=[])) == 0


# --------------------------------------------------------------------------- #
# main() CLI path — filesystem I/O                                              #
# --------------------------------------------------------------------------- #


def test_main_returns_0_on_passing_sidecars(tmp_path: Path) -> None:
    """main() reads two valid sidecars from disk and returns 0 when both pass."""
    baseline_path = tmp_path / "baseline.json"
    agentic_path = tmp_path / "agentic.json"

    baseline_path.write_text(
        json.dumps(
            _sidecar(cases=[_case_record(id="b-01", source_type="file", passed=True)])
        ),
        encoding="utf-8",
    )
    agentic_path.write_text(
        json.dumps(
            _sidecar(
                pipeline="agentic",
                cases=[
                    _case_record(id="a-01", source_type="file", passed=True),
                    _case_record(id="a-dec", source_type="file", expected_kind="decline", passed=True),
                ],
            )
        ),
        encoding="utf-8",
    )

    rc = main([str(baseline_path), str(agentic_path)])
    assert rc == 0


def test_main_returns_1_on_failing_honesty_gate(tmp_path: Path) -> None:
    """main() exits 1 when the honesty gate fails."""
    baseline_path = tmp_path / "baseline.json"
    agentic_path = tmp_path / "agentic.json"

    baseline_path.write_text(
        json.dumps(_sidecar(cases=[_case_record(id="b-01", source_type="file", passed=True)])),
        encoding="utf-8",
    )
    decline_passed = [
        _case_record(id=f"d-{i:02d}", expected_kind="decline", passed=True) for i in range(5)
    ]
    decline_failed = [_case_record(id="d-05", expected_kind="decline", passed=False)]
    agentic_path.write_text(
        json.dumps(_sidecar(pipeline="agentic", cases=decline_passed + decline_failed)),
        encoding="utf-8",
    )

    rc = main([str(baseline_path), str(agentic_path)])
    assert rc == 1


def test_main_returns_1_on_missing_baseline(tmp_path: Path) -> None:
    """main() exits 1 when the baseline sidecar file does not exist."""
    agentic_path = tmp_path / "agentic.json"
    agentic_path.write_text(json.dumps(_sidecar(pipeline="agentic", cases=[])), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main([str(tmp_path / "missing.json"), str(agentic_path)])

    assert exc_info.value.code == 1


def test_main_returns_1_on_invalid_json(tmp_path: Path) -> None:
    """main() exits 1 when a sidecar file contains malformed JSON."""
    baseline_path = tmp_path / "baseline.json"
    agentic_path = tmp_path / "agentic.json"

    baseline_path.write_text("{not valid json", encoding="utf-8")
    agentic_path.write_text(json.dumps(_sidecar(pipeline="agentic", cases=[])), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main([str(baseline_path), str(agentic_path)])

    assert exc_info.value.code == 1


def test_main_returns_1_on_missing_field_in_sidecar(tmp_path: Path) -> None:
    """main() exits 1 when a sidecar is valid JSON but missing required fields."""
    baseline_path = tmp_path / "baseline.json"
    agentic_path = tmp_path / "agentic.json"

    baseline_path.write_text(json.dumps({"pipeline": "current"}), encoding="utf-8")
    agentic_path.write_text(json.dumps(_sidecar(pipeline="agentic", cases=[])), encoding="utf-8")

    rc = main([str(baseline_path), str(agentic_path)])
    assert rc == 1


# --------------------------------------------------------------------------- #
# Parametric honesty threshold sweep                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("pass_count", "total", "expected_ok"),
    [
        (9, 10, True),   # 0.90 == threshold → passes
        (10, 10, True),  # 1.0 → passes
        (8, 10, False),  # 0.80 < 0.90 → fails
        (5, 6, False),   # 0.833… < 0.90 → fails
        (18, 20, True),  # 0.90 == threshold → passes
        (17, 20, False), # 0.85 < 0.90 → fails
    ],
)
def test_honesty_threshold_parametric(pass_count: int, total: int, expected_ok: bool) -> None:
    """Parametric check that the 0.90 boundary is enforced correctly."""
    cases = [
        _case_record(id=f"d-{i:03d}", expected_kind="decline", passed=(i < pass_count))
        for i in range(total)
    ]
    sidecar = _parse(_sidecar(pipeline="agentic", cases=cases))
    ok, fraction, _total = _honesty_gate(sidecar)
    assert ok is expected_ok, (
        f"Expected gate {'pass' if expected_ok else 'fail'} for "
        f"{pass_count}/{total} = {fraction:.3f} vs threshold {HONESTY_THRESHOLD}"
    )
