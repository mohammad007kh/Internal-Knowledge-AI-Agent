# Task: T-010 - migration-source-intent

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (sources carry their purpose)
**Requirement**: FR-001
**Platform**: web | **Subagents Enabled**: yes

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.migration_strategy` | versioned (Alembic) |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python modules) |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. P1 of six stories is source intent metadata: each source carries an admin-authored purpose, AI-proposed example questions and out-of-scope topics, plus optional cross-source hints, governed by a tri-state capability ramp (`pending_ai → ai_set → user_set`). This task lands the expand-only schema migration that those columns require.

### Domain Rules (from data-model §1 + §8 — VERBATIM)

Columns on the `sources` table:

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `purpose` | `Text` | yes | null | Admin-authored business purpose (1-2 sentences). AI never writes this field (FR-002: admin supplies purpose). |
| `example_questions` | `JSONB` (list[str]) | yes | null | ~3 sample questions; AI-proposed after study, admin-editable. |
| `out_of_scope` | `JSONB` (list[str]) | yes | null | Topics this source cannot answer; AI-proposed, admin-editable. |
| `cross_source_hints` | `JSONB` (list[{topic, source_id}]) | yes | null | Optional "for X see source Y" redirects. v1: admin-authored only. |
| `intent_status` | `String(16)` | no | `'pending_ai'` | `pending_ai \| ai_set \| user_set` — one status for the intent bundle. |
| `intent_updated_at` | `DateTime(tz)` | yes | null | Stamped on any intent write (AI or admin). |

Migration plan (§8): `0036_source_intent` — six columns on `sources`, **server defaults**, **index on `intent_status`**. Current Alembic head: **0035** (verified); `down_revision = '0035'`. Expand-only (no destructive change); existing rows get `intent_status='pending_ai'` and degrade gracefully everywhere.

### API Context

Not applicable — DB migration only.

### Gate Criteria

- [ ] Revision id `0036_source_intent`, `down_revision = '0035'`.
- [ ] All six columns created with exact types/nullability above.
- [ ] `intent_status` is NOT NULL with both Python `default='pending_ai'` and `server_default='pending_ai'`.
- [ ] Index created on `intent_status`.
- [ ] `downgrade()` drops the index then all six columns (clean reverse).
- [ ] Expand-only: no column is dropped/altered destructively on existing data.

---

## 🎯 Objective

Create Alembic migration `0036_source_intent` adding the six source-intent columns to `sources` with server defaults and an index on `intent_status`, reversible via a clean `downgrade()`.

## 🛠️ Implementation Details

### Files to Create

- `backend/alembic/versions/0036_source_intent.py` — the migration (revision `0036_source_intent`, `down_revision='0035'`).

### Files to Update (REQUIRED)

- None at code level (the model mapping is T-020). This is a pure schema migration; chained by T-011 (`down_revision='0036'`).

### Code/Logic Requirements

- First read an existing recent migration (e.g. the `0035` head) to copy the project's exact Alembic idiom (imports, revision header style, `sa.dialects.postgresql.JSONB` usage).
- `upgrade()` — add columns in this order:
  - `purpose` → `sa.Text()`, `nullable=True`
  - `example_questions` → `postgresql.JSONB`, `nullable=True`
  - `out_of_scope` → `postgresql.JSONB`, `nullable=True`
  - `cross_source_hints` → `postgresql.JSONB`, `nullable=True`
  - `intent_status` → `sa.String(16)`, `nullable=False`, `server_default='pending_ai'`
  - `intent_updated_at` → `sa.DateTime(timezone=True)`, `nullable=True`
  - then `op.create_index('ix_sources_intent_status', 'sources', ['intent_status'])`
- `downgrade()` — drop the index first, then drop the six columns in reverse.
- Acceptance Criteria:
  - `alembic upgrade head` applies cleanly on a DB at `0035`.
  - `alembic check` reports no pending model/schema drift (after T-020 maps the columns; for THIS task, the up/down cycle is the gate).
  - A downgrade/upgrade round-trip leaves the schema identical.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Database model** → Migration created (`0036_source_intent`)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic downgrade -1
docker compose exec -T backend alembic upgrade head
```
**Success Criteria**: each command exits 0; the upgrade logs `Running upgrade 0035 -> 0036_source_intent`; the downgrade logs `Running downgrade 0036_source_intent -> 0035`; the final re-upgrade reapplies cleanly (proves the round-trip is clean).

**Expected output (upgrade tail)**:
```
INFO  [alembic.runtime.migration] Running upgrade 0035 -> 0036_source_intent
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed (up/down/up cycle)
- [ ] Linter passed
- [ ] Wiring checklist verified
- [ ] Integration verification passed
