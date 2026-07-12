# Task: T-022 - intent-proposal-task

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (system proposes a draft of intent)
**Requirement**: FR-002 + Security rule 1
**Platform**: web | **Subagents Enabled**: yes
**Dependencies**: [T-012-stage-slots-planner-grader](./T-012-stage-slots-planner-grader.md), [T-020-intent-model-and-repo](./T-020-intent-model-and-repo.md), [T-021-intent-sanitization](./T-021-intent-sanitization.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (class-level singletons) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `backend.job_queue` | celery (+ Redis) |
| `conventions.files` | snake_case (Python modules) |
| `testing.unit_framework` | pytest |
| `testing.mocking` | manual (monkeypatch + unittest.mock) |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. After a source is studied, the system proposes a draft of the intent metadata it can infer (example questions + out-of-scope topics) for the admin to review — the admin supplies the business purpose. This task is the Celery proposal task that builds those drafts from the latest schema document via a cheap-tier LLM call, sanitizes them, and writes them via the TOCTOU-safe conditional update.

### Domain Rules (from data-model §1 — VERBATIM)

**Propose semantics are BUNDLE-level (post-review M5):** there is no per-field provenance — re-propose runs only while `intent_status != 'user_set'` and then replaces the AI-writable fields together. Enforced with a conditional UPDATE (`… WHERE intent_status != 'user_set'`) inside the proposal task to prevent a TOCTOU race with a concurrent admin save. The proposal task NEVER writes `purpose` (admin-only field) and NEVER writes `cross_source_hints` (admin-only in v1).

- **Constitution II (LLM Observability)**: the proposal LLM call MUST be Langfuse-traced with a stage name (use the `planner` or a dedicated cheap slot — pick a cheap-tier slot; trace it).
- **Security rule 1**: sanitize the LLM output (T-021) before writing; reject/drop instruction-like items.
- **Idempotency**: mirror `auto_name_source` — short-circuit (`"skipped"`) when `intent_status == 'user_set'` or when no schema doc exists.

### API Context

```yaml
# Triggered by:
POST /api/v1/sources/{source_id}/intent/propose  → enqueues this task (202)
# Also chained post-study (study completion) like auto_name_source chains off sync success.
```

### Gate Criteria

- [ ] Celery task patterned on `auto_name_source.py` (sync wrapper → async `_run`, container singletons via class-level access).
- [ ] Builds proposals from the latest `SchemaDocument` via a cheap-slot LLM call, Langfuse-traced.
- [ ] Sanitizes output via `intent_sanitizer` (T-021) before persisting.
- [ ] Writes ONLY `example_questions` + `out_of_scope` via `propose_intent_conditional` (T-020) — NEVER `purpose`/`cross_source_hints`.
- [ ] Short-circuits ("skipped") when `intent_status == 'user_set'` (TOCTOU + idempotency).

---

## 🎯 Objective

Implement a Celery task that generates AI-proposed source intent (example questions + out-of-scope) from the latest schema document, sanitizes it, and persists it via the bundle-level conditional update, never touching admin-only fields.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/tasks/propose_intent.py` — Celery task `tasks.propose_intent` (sync wrapper around async `_run(source_id)`), mirroring the structure of `auto_name_source.py`.
- `backend/tests/unit/tasks/test_propose_intent.py` — unit tests with a mocked LLM + mocked repo asserting: (a) `user_set` short-circuit returns `"skipped"` and makes no write, (b) sanitization is applied to LLM output before write, (c) `purpose` and `cross_source_hints` are never in the write call, (d) conditional update is the write path.

### Files to Update (REQUIRED)

- `backend/src/tasks/__init__.py` (or the Celery autodiscover list) — register `tasks.propose_intent` so the worker picks it up.
- Study-completion hook — enqueue `tasks.propose_intent` post-study. CAUTION: the study-chaining premise is shaky — `auto_name_source.py`'s docstring says its study-chain is "wired in a follow-up commit" and may not exist yet. So: if `auto_name_source` is already enqueued from the study completion transition, enqueue `propose_intent` at the same site; OTHERWISE add the dispatch to `backend/src/tasks/study_source.py`'s success/completion path directly. The API trigger (T-023 POST propose) is the guaranteed entry point either way. (Read the relevant call site first to match the dispatch shim idiom.)

### Code/Logic Requirements

- `_run(source_id)`:
  1. Load source; if `intent_status == 'user_set'` → return `{"status": "skipped"}` (no LLM call).
  2. Load the latest `SchemaDocument` for the source; if none → `"skipped"`.
  3. Resolve a cheap-tier LLM slot via the container (class-level singleton access, same reasoning as `auto_name_source._build_profiler_factory`), build a prompt over the schema projection, call it **Langfuse-traced** (Constitution II).
  4. Parse structured output → candidate `example_questions` (≤5) + `out_of_scope` (≤10).
  5. Sanitize via `intent_sanitizer` (T-021) — drop/reject instruction-like items, enforce caps.
  6. Persist via `propose_intent_conditional(source_id, example_questions=..., out_of_scope=...)` (T-020). NEVER pass `purpose` or `cross_source_hints`.
  7. Return a small status dict (`"ai_set"` / `"skipped"`).
- `autoretry_for=(Exception,)` backoff like `auto_name_source`.
- Acceptance Criteria (mocked LLM):
  - `user_set` source → no LLM call, no write, `"skipped"`.
  - LLM returns an item starting `"Ignore prior"` → sanitizer drops/rejects it; it never reaches the repo.
  - Write call args contain only `example_questions` + `out_of_scope`.

## 🔌 Wiring Checklist

### Web
- [ ] **Backend route** → enqueued by POST `/intent/propose` (T-023)

### Shared (All Platforms)
- [x] **Service registration** → task registered for Celery autodiscover
- [x] **Lifecycle hook** → enqueued from study-completion transition (chained, like `auto_name_source`)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/tasks/test_propose_intent.py --no-cov -q
docker compose exec -T backend ruff check src/tasks/propose_intent.py
docker compose exec -T backend mypy src/tasks/propose_intent.py
```
**Success Criteria**: pytest reports `passed` including the `user_set` short-circuit, sanitization-applied, and never-writes-purpose tests; ruff `All checks passed!`; mypy `Success: no issues found`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified (registered + chained)
- [ ] Integration verification passed
