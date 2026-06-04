# Task: T-080 - clarify-options-backend

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US4 (when the question is ambiguous, ask — with choices)
**Requirement**: FR-014, FR-015
**Dependencies**: [T-052-planner-node](./T-052-planner-node.md) (cross-batch — the planner node + its `needs_clarification` path are generated in parallel under Slice C)

---

## 📋 Embedded Context (READ THIS FIRST)

<!--
  SELF-CONTAINED TASK (Constitution Directive 8):
  This section contains ALL context needed to implement this task.
  Do NOT read plan.md, spec.md, stations, or subagents.
-->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic v2) |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `conventions.classes` | PascalCase |
| `conventions.constants` | SCREAMING_SNAKE_CASE |
| `tooling.lint` | ruff (NEVER eslint/jest) |

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 4 (this task): when planning cannot confidently choose between real
alternatives, the system pauses BEFORE executing and asks the user with 2-4
concrete options plus a free-text fallback. This task extends the existing
`clarification` SSE event with the structured options payload and emits it from
the planner's `needs_clarification` path.

### Architecture (load-bearing — terminal SSE, history-based resume)

- Clarification is a **TERMINAL** event for the turn — it ends the turn. There
  is **NO `interrupt()` / checkpointer / cross-turn pending state** (data-model
  §2: no `clarification_pending` field — a cross-turn pending field would be
  vestigial).
- The planner's `needs_clarification` path emits the event **BEFORE any
  execution** and ends the turn.
- The user's reply arrives as the **NEXT turn** (history-based resume) — the
  chosen option's LABEL posts as a normal user message (handled on the frontend
  in T-081; the backend just receives it as the next user turn).

### Extended `clarification` SSE event (COPIED VERBATIM from contracts/sse-events.md)

```jsonc
event: clarification
data: {
  "question": "Which users did you mean?",
  "options": [
    {"id": "hr", "label": "Employees", "hint": "HR database", "recommended": false},
    {"id": "crm", "label": "Customers", "hint": "CRM file", "recommended": true},
    {"id": "both", "label": "Both"}
  ],
  "allow_free_text": true
}
```

- 2-4 options. `hint` and `recommended` optional per option. `allow_free_text`
  is the "Something else…" escape hatch.
- Absent payload = legacy free-text behavior (the existing event still works
  with no `options`). Additive only.

### Security rule 2 (HIGH — ENFORCED HERE)

> Clarification options are generated **exclusively from the requesting user's
> permitted source set**; an option may NEVER name an inaccessible source.

This is the same permission-clipping discipline as `source_router` (FX41
lesson — re-clip against the user's permitted set). The options derive from the
sources the user can access; never surface a source name the user cannot see.

### Gate Criteria

- [ ] `clarification` event gains an optional structured `options[]` payload (2-4 options) + `allow_free_text`; legacy no-options emission still valid (additive).
- [ ] Emitted from the planner `needs_clarification` path BEFORE any execution; TERMINAL for the turn.
- [ ] NO `interrupt()`/checkpointer/cross-turn pending state.
- [ ] Options generated EXCLUSIVELY from the user's permitted source set (security rule 2).
- [ ] Schema validated (Pydantic v2): 2 ≤ len(options) ≤ 4.

---

## 🎯 Objective

Extend the `clarification` SSE event schema with the structured options payload
and emit it from the planner's `needs_clarification` path (terminal, pre-execution,
history-based resume), with options drawn exclusively from the requesting user's
permitted source set.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/agent/test_clarify_options.py` - pytest: (a) the extended `clarification` event serializes the options payload matching the wire contract; (b) 2-4 options enforced (1 or 5 options → validation error); (c) legacy emission with NO options still valid; (d) options are clipped to the user's permitted source set (an option referencing an inaccessible source is excluded / never produced); (e) the clarification path is terminal — no execution events follow and no checkpointer/interrupt is used.

### Files to Update (REQUIRED)

- `backend/src/schemas/chat.py` - extend the `clarification` event payload: add optional `options: list[ClarificationOption] | None` and `allow_free_text: bool` to the clarification data model; define `ClarificationOption` (`id: str`, `label: str`, `hint: str | None = None`, `recommended: bool | None = None`) as a Pydantic v2 model with `2 ≤ len(options) ≤ 4` validation. Additive — do not break the legacy free-text shape.
- `backend/src/services/chat_stream_service.py` (the chat stream service that emits SSE events) - emit the extended `clarification` event from the planner's `needs_clarification` path BEFORE any step execution; end the turn after emission (terminal). Build `options` ONLY from the requesting user's permitted source set (re-clip like `source_router`).

### Code/Logic Requirements

- Pydantic v2 validation (registry `validation_approach`): `ClarificationOption` + the options-length constraint (2-4). Error handling = exceptions (registry) — invalid option sets raise a clear validation error.
- The emission is TERMINAL: after the clarification event, the turn ends (a `done`/terminal frame closes the stream). No execution (`step`) events are emitted, no `interrupt()`, no checkpointer, no cross-turn pending state field.
- Options are generated EXCLUSIVELY from the user's permitted source set (security rule 2). Reuse the existing permission-clipping path used by `source_router`; an option's `hint`/`label` must never name a source the user cannot access.
- `allow_free_text` defaults true (the "Something else…" escape hatch always available in v1).
- Wire format unchanged (`event: clarification\n` + `data: <json>\n\n`); only the JSON payload is extended.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **API client** → SSE event consumed by both frontend stream hooks (handled in T-081); backend only emits here
- [ ] **Database model** → N/A (no persistence; transient event + history echo per data-model §4)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_clarify_options.py --no-cov -q
```
**Success Criteria**: all tests pass — extended payload serializes to the wire
contract; 2-4 option constraint enforced; legacy no-options emission valid;
options clipped to the permitted source set; clarification path terminal (no
execution events, no interrupt/checkpointer).

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/unit/agent/test_clarify_options.py --no-cov -q
```

Lint:
```bash
docker compose exec -T backend ruff check src/schemas/chat.py src/services/chat_stream_service.py
```

## 📝 Completion Log

- [ ] `clarification` event extended with `ClarificationOption[]` (2-4) + `allow_free_text` (additive)
- [ ] Emitted from planner `needs_clarification` path, pre-execution, TERMINAL
- [ ] NO interrupt/checkpointer/cross-turn pending state
- [ ] Options clipped to the user's permitted source set (security rule 2)
- [ ] Unit tests pass
- [ ] `ruff check` clean
