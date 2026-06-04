# Task: T-012 - stage-slots-planner-grader

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 / US3 (planning + verification enabler)
**Requirement**: FR-002 / FR-010 enabler
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
| `code_patterns.dependency_injection` | container (dependency-injector IoC) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `testing.unit_framework` | pytest |
| `testing.mocking` | manual (pytest monkeypatch + unittest.mock) |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. The planner decomposes questions into dependent steps and a `retrieval_grader` slot powers light-everywhere + heavy-for-DB verification. Both are new admin-tunable LLM stage slots that must be seeded and resolvable before the planner/verify nodes can call them.

### Domain Rules (from data-model §7 — VERBATIM)

`STAGES` registry extends with two admin-tunable slots: **`planner`** and **`retrieval_grader`** (shared by light + heavy verification; R3). Concrete paths (Context-Pinning fix): defaults live in `backend/src/agent/stage_defaults.py` (`STAGE_DEFAULTS` dict); idempotent seeding + link-verification in `backend/src/services/startup_seed.py` (every slot in `STAGES` must be seeded/linked at startup). Existing 11 slots unchanged; `reflector` remains independent and default-OFF (Constitution IV).

- **Cheap-tier, low temperature**: both new slots run cold/structured (mirror `source_router`/`retrieval` which are `temperature=0.0`). Use low temperature defaults.
- **Constitution I (Interface-First)**: slots resolve via `AIModelResolver`; tests mock the resolver.
- **Existing `STAGE_DEFAULTS` entries** (do NOT modify) include `source_router`/`retrieval` at `temperature=0.0` — copy that idiom for the two new slots.

### API Context

Admin LLM-settings surface: stages exposed via `backend/src/api/v1/admin/llm_settings.py` (`STAGES` + `STAGE_META`). Adding the two slots there lets admins tune temperature/max_tokens/prompt.

### Gate Criteria

- [ ] `planner` and `retrieval_grader` added to `STAGE_DEFAULTS` with low (≈0.0–0.1) temperature.
- [ ] Both slots added to `STAGES`/`STAGE_META` in `llm_settings.py`.
- [ ] `startup_seed` seeds + links both idempotently (re-run is a no-op).
- [ ] Both slots resolve through `AIModelResolver` (proven by a mocked-resolver test).
- [ ] `reflector` untouched and still default-OFF.

---

## 🎯 Objective

Register two new admin-tunable LLM stage slots — `planner` and `retrieval_grader` — with cheap-tier low-temperature defaults, idempotent startup seeding/linking, and admin-settings exposure, so the planner and verification nodes can resolve a model per slot.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/services/test_startup_seed_agentic_slots.py` — asserts both slots are seeded/linked idempotently (second run = no-op) and that each resolves via a mocked `AIModelResolver`.

### Files to Update (REQUIRED)

- `backend/src/agent/stage_defaults.py` — add `STAGE_DEFAULTS["planner"]` and `STAGE_DEFAULTS["retrieval_grader"]` (low temperature; pick `max_tokens` consistent with short structured output, e.g. ≈1024). Match the existing `StageDefaults(...)` idiom in this file.
- `backend/src/services/startup_seed.py` — ensure the seeding/link-verification loop covers the two new slots (it iterates `STAGES`; confirm both names flow through `ensure_default_stage_configs`).
- `backend/src/api/v1/admin/llm_settings.py` — add `planner` and `retrieval_grader` to `STAGES` and `STAGE_META` (label + description) so admins can tune them.

### Code/Logic Requirements

- Read all three target files before editing; mirror the existing slot declarations exactly.
- Defaults (cheap-tier, low temperature):
  - `STAGE_DEFAULTS["planner"] = StageDefaults(temperature=0.0, max_tokens=1024)`
  - `STAGE_DEFAULTS["retrieval_grader"] = StageDefaults(temperature=0.0, max_tokens=1024)`
- Seeding MUST be idempotent: re-seeding an existing row does not overwrite admin edits (same "updating the default dict does NOT rewrite existing rows" rule documented in `stage_defaults.py`).
- Acceptance Criteria:
  - Startup seed run twice → second run links/finds existing rows, writes nothing new.
  - `AIModelResolver` (mocked) returns a model for both `planner` and `retrieval_grader`.
  - `STAGES` length increases by exactly 2; `reflector` entry unchanged.

## 🔌 Wiring Checklist

### Web
- [x] **Backend route** → `STAGES`/`STAGE_META` updated so admin LLM-settings routes expose both slots
- [ ] **Frontend page** → N/A (existing admin settings UI iterates STAGES generically)

### Shared (All Platforms)
- [x] **Service registration** → `startup_seed` seeds/links both slots at startup

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/services/test_startup_seed_agentic_slots.py --no-cov -q
docker compose exec -T backend ruff check src/agent/stage_defaults.py src/services/startup_seed.py src/api/v1/admin/llm_settings.py
```
**Success Criteria**: pytest reports `passed` for the idempotent-seed test and the mocked-resolver resolution test for both slots; ruff prints `All checks passed!`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified (STAGES + startup_seed)
- [ ] Integration verification passed
