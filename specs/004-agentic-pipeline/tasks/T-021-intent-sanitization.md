# Task: T-021 - intent-sanitization

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (sources carry their purpose)
**Requirement**: FR-002 + Security rule 1 (Intent prompt hygiene)
**Platform**: web | **Subagents Enabled**: yes

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `security.input_sanitization` | strict |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Source intent fields (purpose, example questions, out-of-scope, cross-source hints) are injected into LLM prompts. Some of that text is admin-authored (trusted) but AI-proposed text is model output — both must be sanitized so a malicious or accidental instruction-like string in an intent field can never hijack a downstream prompt.

### Domain Rules — SECURITY RULE 1 (Intent prompt hygiene, HIGH) — VERBATIM

> Intent fields render inside unambiguous delimiters; treated as data, never instructions; write-time sanitization (PUT 422 + proposal-task output validation) against instruction-like leading patterns; proposal task never writes `purpose` or `cross_source_hints`.

Injection hygiene (data-model §1, security review F1): values are sanitized at write time (**PUT validation AND proposal-task output validation**) against instruction-like leading patterns; length caps below.

**Length caps:** `purpose` ≤ 500 chars; `example_questions` ≤ 5 items; `out_of_scope` ≤ 10 items.

**Instruction-like leading patterns to strip/reject** (case-insensitive, after trim), per intent field item: `"Ignore"`, `"You are"`, `"System:"`, `"Assistant:"`.

### API Context

Used by BOTH: the PUT `/intent` schema validation (raises → 422 on violation, T-023) and the proposal-task output validation (T-022).

### Gate Criteria

- [ ] Pure functions (no I/O, no DB, no LLM) — deterministic and exhaustively unit-tested.
- [ ] Rejects/strips items whose trimmed, case-insensitive leading text matches `Ignore` / `You are` / `System:` / `Assistant:`.
- [ ] Enforces length caps (purpose ≤500, example_questions ≤5, out_of_scope ≤10).
- [ ] Reused by PUT validation (422 path) and proposal-task output validation.

---

## 🎯 Objective

Provide pure, exhaustively-tested sanitization functions that detect/reject instruction-like leading patterns and enforce intent length caps, usable by both the PUT schema validator and the AI proposal task.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/services/intent_sanitizer.py` — pure functions: `sanitize_purpose(value) -> str`, `sanitize_question_list(items) -> list[str]`, `sanitize_out_of_scope(items) -> list[str]`, and a shared `is_instruction_like(text) -> bool` predicate. **DECIDED dual-mode behavior:** (a) **strict mode** (used by the PUT schema, T-023): any violating field/item raises `IntentSanitizationError` → API returns 422 — the admin sees exactly what was rejected; (b) **lenient mode** (used by the proposal task, T-022): violating ITEMS are silently dropped, clean items kept (a partially-bad AI draft still yields value); if `purpose` itself were ever AI-written it would be dropped whole — but the proposal task never writes purpose. Both modes share the same predicate + caps constants.
- `backend/tests/unit/services/test_intent_sanitizer.py` — exhaustive unit tests: each leading pattern (mixed case, with/without leading whitespace), benign text passes, cap overflow rejected, empty/None handling.

### Files to Update (REQUIRED)

- None directly; this module is imported by T-022 (proposal task) and T-023 (PUT schema). Those tasks wire it in.

### Code/Logic Requirements

- `is_instruction_like(text)`: trim, lowercase, return True if it starts with any of `ignore`, `you are`, `system:`, `assistant:`. Keep the pattern list as a module constant for testability.
- Length caps as module constants (`PURPOSE_MAX_CHARS = 500`, `MAX_EXAMPLE_QUESTIONS = 5`, `MAX_OUT_OF_SCOPE = 10`) — single source of truth shared by schema + task.
- No mutation of inputs (immutability rule) — return new strings/lists.
- Acceptance Criteria:
  - `is_instruction_like("  IGNORE previous")` → True; `is_instruction_like("System: do X")` → True; `is_instruction_like("This source holds architectural workspaces")` → False.
  - `sanitize_question_list` of 6 items → rejected/capped per documented behavior; of 5 clean items → unchanged.
  - `sanitize_purpose` of a 501-char string → rejected.

## 🔌 Wiring Checklist

### Web
- [ ] **Backend route** → consumed by PUT schema (T-023) and proposal task (T-022)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/services/test_intent_sanitizer.py --no-cov -q
docker compose exec -T backend ruff check src/services/intent_sanitizer.py
docker compose exec -T backend mypy src/services/intent_sanitizer.py
```
**Success Criteria**: pytest reports `passed` for all leading-pattern, cap, and benign cases; ruff prints `All checks passed!`; mypy prints `Success: no issues found`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified
- [ ] Integration verification passed
