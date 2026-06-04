# Task: T-020 - intent-model-and-repo

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (sources carry their purpose)
**Requirement**: FR-001
**Platform**: web | **Subagents Enabled**: yes
**Dependencies**: [T-010-migration-source-intent](./T-010-migration-source-intent.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository (Protocol-based interfaces) |
| `code_patterns.dependency_injection` | container |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python modules) |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. P1 is source intent: admin-authored purpose + AI-proposed example questions / out-of-scope, under a tri-state capability ramp. This task maps the new columns on the `Source` model and adds repository methods for reading, admin-saving, and AI-proposing intent — including the TOCTOU-safe conditional update that protects an admin save from a concurrent proposal task.

### Domain Rules (from data-model §1 — VERBATIM)

**State transitions:** `pending_ai → ai_set` (studying/auto-intent task writes proposals) · `ai_set → user_set` (admin saves review) · `user_set → user_set` (admin edits) · re-study NEVER downgrades `user_set` content (mirror of auto-naming's "never overwrite human values").

**Propose semantics are BUNDLE-level (post-review M5):** there is no per-field provenance — re-propose runs only while `intent_status != 'user_set'` and then replaces the AI-writable fields together (matching the auto-naming row-level precedent). Enforced with a conditional UPDATE (`… WHERE intent_status != 'user_set'`) inside the proposal task to prevent a TOCTOU race with a concurrent admin save. The proposal task NEVER writes `purpose` (admin-only field) and NEVER writes `cross_source_hints` (admin-only in v1).

**Validation rules (from requirements):** `purpose` ≤ ~500 chars; `example_questions` ≤ 5 items; `out_of_scope` ≤ 10 items (router token budget protection). `intent_status` transitions only along the ramp (no `user_set → ai_set`).

Columns (already migrated by T-010): `purpose Text`, `example_questions JSONB`, `out_of_scope JSONB`, `cross_source_hints JSONB`, `intent_status String(16) NOT NULL default 'pending_ai'`, `intent_updated_at DateTime(tz)`.

### API Context

Repo methods back the GET/PUT/POST-propose endpoints (T-023). PUT = admin save → `user_set`; propose = bundle conditional update.

### Gate Criteria

- [ ] Six intent columns mapped on `Source` mirroring the existing auto-naming pattern (`name_status`/`description_status`).
- [ ] `get_intent`, `update_intent`, `propose_intent_conditional` repo methods present.
- [ ] `update_intent` sets `intent_status='user_set'` and stamps `intent_updated_at`.
- [ ] `propose_intent_conditional` uses `WHERE intent_status != 'user_set'`, NEVER writes `purpose` or `cross_source_hints`, stamps `intent_updated_at`.
- [ ] Caps enforced at model/schema level: `purpose` ≤ 500 chars, `example_questions` ≤ 5, `out_of_scope` ≤ 10.
- [ ] A test proves `user_set` rows are untouched by the conditional update.

---

## 🎯 Objective

Map the six source-intent columns on the `Source` model and add `SourceRepository` methods to read intent, save an admin review (→ `user_set`), and conditionally apply AI proposals without clobbering admin-set rows.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/repositories/test_source_intent_repo.py` — unit tests for `get_intent`, `update_intent` (status flip + timestamp), and `propose_intent_conditional` (incl. a test proving a `user_set` row is NOT modified by the conditional update; and that `purpose`/`cross_source_hints` are never written by propose).

### Files to Update (REQUIRED)

- `backend/src/models/source.py` — add the six mapped columns mirroring the `name_status`/`description_status` declaration idiom already in the model.
- `backend/src/repositories/source_repository.py` (existing `SourceRepository`) — add the three methods. (Read the file first to match its session/async idiom.)

### Code/Logic Requirements

- Model columns: `purpose: Mapped[str | None]`, `example_questions: Mapped[list | None]` (JSONB), `out_of_scope: Mapped[list | None]` (JSONB), `cross_source_hints: Mapped[list | None]` (JSONB), `intent_status: Mapped[str]` (default `'pending_ai'`), `intent_updated_at: Mapped[datetime | None]` (tz-aware). Mirror the auto-naming columns' exact mapping style.
- `get_intent(source_id) -> <intent fields>`: returns the six fields (or raises/None if source missing — match repo's existing not-found convention).
- `update_intent(source_id, *, purpose?, example_questions?, out_of_scope?, cross_source_hints?)`: admin save — provided fields replace stored values; sets `intent_status='user_set'`; stamps `intent_updated_at=now(tz)`. Caps enforced (purpose ≤500, example_questions ≤5, out_of_scope ≤10) — raise on violation (exceptions are the registry error strategy).
- `propose_intent_conditional(source_id, *, example_questions, out_of_scope)`: bundle-level conditional UPDATE:
  - `UPDATE sources SET example_questions=:eq, out_of_scope=:oos, intent_status='ai_set', intent_updated_at=now() WHERE id=:id AND intent_status != 'user_set'`
  - MUST NOT include `purpose` or `cross_source_hints` in the SET clause.
  - Return whether a row was affected (0 = a concurrent admin save won the race; short-circuit semantics for the caller).
- Acceptance Criteria:
  - `update_intent` → `intent_status == 'user_set'` and `intent_updated_at` is set.
  - `propose_intent_conditional` on a `user_set` row affects 0 rows and leaves all fields unchanged.
  - `propose_intent_conditional` on a `pending_ai`/`ai_set` row writes only `example_questions`/`out_of_scope` + status/timestamp.
  - Cap violations raise.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Database model** → Columns mapped on `Source` (migration is T-010)
- [ ] **API client** → consumed by endpoints in T-023

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/repositories/test_source_intent_repo.py --no-cov -q
docker compose exec -T backend ruff check src/models/source.py src/repositories/source_repository.py
docker compose exec -T backend mypy src/repositories/source_repository.py
```
**Success Criteria**: pytest reports `passed` including the `user_set`-untouched and propose-never-writes-purpose tests; ruff prints `All checks passed!`; mypy prints `Success: no issues found`.

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
