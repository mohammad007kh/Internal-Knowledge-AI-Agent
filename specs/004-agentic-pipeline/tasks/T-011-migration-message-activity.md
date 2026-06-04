# Task: T-011 - migration-message-activity

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US5 (the agent's thinking is visible, persisted compactly)
**Requirement**: FR-018
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
| `code_patterns.error_handling` | exceptions |
| `database.tenancy_model` | single_tenant |
| `database.migration_strategy` | versioned (Alembic) |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python modules) |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Story 5's two-layer thinking UX persists a *compact* activity summary on each chat message so the activity view survives conversation reloads (full step payloads stay stream-only). This task lands the expand-only column + a DB-level size guard for that summary.

### Domain Rules (from data-model §3 + §8 + security rule 5 — VERBATIM)

Activity Record (compact persistence on `chat_messages`):

| Column | Type | Null | Notes |
|---|---|---|---|
| `activity_summary` | `JSONB` | yes | Compact shape. Null for pre-feature + non-agentic messages. |

Migration (§8): `0037_message_activity` — `activity_summary JSONB` on `chat_messages`, plus a DB-level guard for compact persistence (security review F5): **`CHECK (pg_column_size(activity_summary) <= 16384)`** — application code additionally caps `roles[].line` at 200 chars and step labels at 200 chars; `step` SSE `summary` is application-generated narration ("first 3 items + count"), never raw row slices. `down_revision = '0036'`. Expand-only; existing rows get `activity_summary=NULL` and degrade gracefully (UI hides what's absent).

### API Context

Not applicable — DB migration only.

### Gate Criteria

- [ ] Revision id `0037_message_activity`, `down_revision = '0036'`.
- [ ] `activity_summary` JSONB nullable column on `chat_messages`.
- [ ] DB-level CHECK constraint: `pg_column_size(activity_summary) <= 16384`.
- [ ] `downgrade()` drops the constraint then the column.
- [ ] Expand-only: no destructive change to existing rows.

---

## 🎯 Objective

Create Alembic migration `0037_message_activity` adding a nullable `activity_summary` JSONB column to `chat_messages` plus a `pg_column_size(...) <= 16384` CHECK constraint, reversible via `downgrade()`.

## 🛠️ Implementation Details

### Files to Create

- `backend/alembic/versions/0037_message_activity.py` — the migration (revision `0037_message_activity`, `down_revision='0036'`).

### Files to Update (REQUIRED)

- None at code level (model mapping for `activity_summary` belongs to the message repo/UX slice). Pure schema migration; chains off T-010.

### Code/Logic Requirements

- Read `0036_source_intent.py` (from T-010) first to keep the revision-header/import idiom consistent.
- `upgrade()`:
  - `op.add_column('chat_messages', sa.Column('activity_summary', postgresql.JSONB, nullable=True))`
  - `op.create_check_constraint('ck_chat_messages_activity_summary_size', 'chat_messages', 'pg_column_size(activity_summary) <= 16384')`
- `downgrade()`:
  - `op.drop_constraint('ck_chat_messages_activity_summary_size', 'chat_messages', type_='check')`
  - `op.drop_column('chat_messages', 'activity_summary')`
- Acceptance Criteria:
  - `alembic upgrade head` applies cleanly on a DB at `0036`.
  - Inserting an `activity_summary` larger than 16 KiB is rejected by the DB (constraint active).
  - Down/up round-trip leaves the schema identical.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Database model** → Migration created (`0037_message_activity`)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic downgrade -1
docker compose exec -T backend alembic upgrade head
```
**Success Criteria**: each command exits 0; upgrade logs `Running upgrade 0036_source_intent -> 0037_message_activity`; downgrade logs the reverse; final re-upgrade reapplies cleanly.

**Expected output (upgrade tail)**:
```
INFO  [alembic.runtime.migration] Running upgrade 0036_source_intent -> 0037_message_activity
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed (up/down/up cycle)
- [ ] Linter passed
- [ ] Wiring checklist verified
- [ ] Integration verification passed
