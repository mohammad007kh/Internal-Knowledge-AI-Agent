"""Eval case schema (Pydantic v2) + JSON-golden case loaders.

Defines the frozen contract for a single evaluation case and the loaders that
parse the JSON-golden case set under ``backend/evals/cases/``.

Security Rule 4 (Eval Data Hygiene): every case MUST carry
``"data_source": "synthetic"``. The schema enforces this via a ``Literal`` so
any other value is a validation error, and the loader surfaces the offending
file + field on failure. The repo is PUBLIC — fixtures contain NO real names,
PII, URLs, or business data.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

SourceType = Literal["file", "web", "database", "multi"]
ExpectedKind = Literal["answer", "decline"]


class EvalCaseError(ValueError):
    """Raised when a case file fails to parse or validate.

    Subclasses :class:`ValueError` (registry: error_handling = exceptions) so
    callers can catch it specifically while it still behaves like a value
    error. The message always names the offending file and, where known, the
    field at fault.
    """


class Fixtures(BaseModel):
    """Fixture references attached to a case.

    ``seed`` is a path RELATIVE to ``backend/`` (e.g.
    ``evals/fixtures/cctp-mini.sql``). The actual seed SQL is authored in
    T-041; this task may reference paths T-041 will create.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: str


class EvalCase(BaseModel):
    """A single frozen evaluation case (immutable).

    Honesty cases (``expected_kind == "decline"``) encode the canonical decline
    phrasing in ``golden_answer`` and keep ``must_not_fabricate`` true. ``multi``
    cases MUST attach ``fixtures`` (they chain a file + a database source).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_type: SourceType
    question: str
    expected_kind: ExpectedKind
    golden_answer: str
    must_include: list[str] = []
    must_not_fabricate: bool = True
    fixtures: Fixtures | None = None
    # Security Rule 4 — REQUIRED, must equal the literal "synthetic".
    data_source: Literal["synthetic"]

    @model_validator(mode="after")
    def _check_non_empty_and_multi_fixtures(self) -> EvalCase:
        if not self.id.strip():
            raise ValueError("id must be non-empty")
        if not self.question.strip():
            raise ValueError("question must be non-empty")
        if not self.golden_answer.strip():
            raise ValueError("golden_answer must be non-empty")
        if self.source_type == "multi" and self.fixtures is None:
            raise ValueError("multi cases require 'fixtures'")
        return self


def load_case(path: str | Path) -> EvalCase:
    """Load and validate a single case file.

    Raises :class:`EvalCaseError` naming the file (and field, when known) on any
    JSON or schema validation failure.
    """
    case_path = Path(path)
    try:
        raw = case_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalCaseError(f"{case_path}: could not read file: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvalCaseError(f"{case_path}: invalid JSON: {exc}") from exc

    try:
        return EvalCase.model_validate(payload)
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(str(loc) for loc in err["loc"]) for err in exc.errors()
        )
        raise EvalCaseError(
            f"{case_path}: schema validation failed (fields: {fields or '<root>'})"
        ) from exc


def load_all_cases(cases_dir: str | Path) -> list[EvalCase]:
    """Recursively load every ``*.json`` case under ``cases_dir``.

    Asserts ``id`` uniqueness across the whole set. Raises
    :class:`EvalCaseError` if the directory is missing or any id collides.
    """
    root = Path(cases_dir)
    if not root.is_dir():
        raise EvalCaseError(f"{root}: cases directory not found")

    cases = [load_case(p) for p in sorted(root.rglob("*.json"))]

    duplicates = [cid for cid, count in Counter(c.id for c in cases).items() if count > 1]
    if duplicates:
        raise EvalCaseError(f"duplicate case id(s) across set: {sorted(duplicates)}")

    return cases
