"""Schema validation + data_source enforcement for the frozen eval case set.

Discovers EVERY ``*.json`` under ``backend/evals/cases/``, parses each against
:class:`EvalCase`, and asserts the Security Rule 4 invariant
(``data_source == "synthetic"``) plus the task's count and uniqueness gates.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.schema import (
    EvalCase,
    EvalCaseError,
    Fixtures,
    load_all_cases,
    load_case,
)

# backend/ root = parents[3] of this file
# tests/unit/evals/test_eval_schema.py -> evals(0) -> unit(1) -> tests(2) -> backend(3)
BACKEND_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = BACKEND_ROOT / "evals" / "cases"

CASE_FILES = sorted(CASES_DIR.rglob("*.json"))


def _minimal_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "x-sample-01",
        "source_type": "file",
        "question": "What is the synthetic answer?",
        "expected_kind": "answer",
        "golden_answer": "The synthetic answer is 42.",
        "must_include": ["42"],
        "must_not_fabricate": True,
        "fixtures": None,
        "data_source": "synthetic",
    }
    base.update(overrides)
    return base


# --- discovery sanity -------------------------------------------------------


def test_cases_directory_exists() -> None:
    assert CASES_DIR.is_dir(), f"missing cases dir: {CASES_DIR}"


def test_case_files_discovered() -> None:
    assert CASE_FILES, "no *.json case files discovered"


# --- every committed case parses + is synthetic -----------------------------


@pytest.mark.parametrize("case_path", CASE_FILES, ids=lambda p: p.stem)
def test_every_case_parses_and_is_synthetic(case_path: Path) -> None:
    case = load_case(case_path)
    assert isinstance(case, EvalCase)
    assert case.data_source == "synthetic"


def test_load_all_cases_all_synthetic() -> None:
    cases = load_all_cases(CASES_DIR)
    assert cases
    assert all(c.data_source == "synthetic" for c in cases)


# --- count + structural gates -----------------------------------------------


def test_total_count_in_target_range() -> None:
    cases = load_all_cases(CASES_DIR)
    assert 20 <= len(cases) <= 30, f"total cases out of 20-30 range: {len(cases)}"


def test_decline_count_in_target_range() -> None:
    cases = load_all_cases(CASES_DIR)
    declines = [c for c in cases if c.expected_kind == "decline"]
    assert 10 <= len(declines) <= 15, f"declines out of 10-15 range: {len(declines)}"


def test_multi_count_in_target_range() -> None:
    cases = load_all_cases(CASES_DIR)
    multi = [c for c in cases if c.source_type == "multi"]
    assert 3 <= len(multi) <= 5, f"multi out of 3-5 range: {len(multi)}"


def test_case_ids_unique() -> None:
    cases = load_all_cases(CASES_DIR)
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids present"


def test_multi_cases_have_fixtures() -> None:
    cases = load_all_cases(CASES_DIR)
    for c in cases:
        if c.source_type == "multi":
            assert c.fixtures is not None, f"multi case {c.id} missing fixtures"


def test_decline_cases_must_not_fabricate() -> None:
    cases = load_all_cases(CASES_DIR)
    for c in cases:
        if c.expected_kind == "decline":
            assert c.must_not_fabricate is True, f"decline {c.id} must set must_not_fabricate"


def test_source_types_span_all_four() -> None:
    cases = load_all_cases(CASES_DIR)
    present = {c.source_type for c in cases}
    assert present == {"file", "web", "database", "multi"}, present


# --- schema unit behaviour --------------------------------------------------


def test_valid_minimal_case_is_frozen() -> None:
    case = EvalCase.model_validate(_minimal_payload())
    assert case.must_not_fabricate is True
    with pytest.raises(Exception):
        case.id = "mutated"  # type: ignore[misc]


def test_defaults_applied() -> None:
    payload = _minimal_payload()
    del payload["must_include"]
    del payload["must_not_fabricate"]
    case = EvalCase.model_validate(payload)
    assert case.must_include == []
    assert case.must_not_fabricate is True


def test_data_source_rejects_non_synthetic() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(data_source="real"))


def test_data_source_required() -> None:
    payload = _minimal_payload()
    del payload["data_source"]
    with pytest.raises(Exception):
        EvalCase.model_validate(payload)


def test_invalid_source_type_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(source_type="api"))


def test_invalid_expected_kind_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(expected_kind="maybe"))


def test_empty_id_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(id="  "))


def test_empty_question_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(question=""))


def test_empty_golden_answer_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(golden_answer=""))


def test_multi_without_fixtures_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(source_type="multi", fixtures=None))


def test_multi_with_fixtures_valid() -> None:
    case = EvalCase.model_validate(
        _minimal_payload(
            source_type="multi",
            fixtures={"seed": "evals/fixtures/cctp-mini.sql"},
        )
    )
    assert isinstance(case.fixtures, Fixtures)
    assert case.fixtures.seed == "evals/fixtures/cctp-mini.sql"


def test_unknown_field_rejected() -> None:
    with pytest.raises(Exception):
        EvalCase.model_validate(_minimal_payload(unexpected="boom"))


# --- loader error handling --------------------------------------------------


def test_load_case_invalid_json_raises_eval_case_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json ", encoding="utf-8")
    with pytest.raises(EvalCaseError) as exc:
        load_case(bad)
    assert "invalid JSON" in str(exc.value)
    assert str(bad) in str(exc.value)


def test_load_case_schema_error_names_field(tmp_path: Path) -> None:
    payload = _minimal_payload(data_source="real")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvalCaseError) as exc:
        load_case(bad)
    assert "data_source" in str(exc.value)


def test_load_case_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalCaseError):
        load_case(tmp_path / "does-not-exist.json")


def test_load_all_cases_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalCaseError):
        load_all_cases(tmp_path / "nope")


def test_load_all_cases_duplicate_id_raises(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(
            json.dumps(_minimal_payload(id="dup-01")), encoding="utf-8"
        )
    with pytest.raises(EvalCaseError) as exc:
        load_all_cases(tmp_path)
    assert "duplicate" in str(exc.value).lower()
