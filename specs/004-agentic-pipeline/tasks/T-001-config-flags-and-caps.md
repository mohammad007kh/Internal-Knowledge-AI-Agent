# Task: T-001 - config-flags-and-caps

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US6 (bounded cost & rollout)
**Requirement**: FR-019, FR-026
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
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `conventions.constants` | SCREAMING_SNAKE_CASE |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Six prioritized stories: P1 source intent metadata (hybrid authoring, capability-ramp authority), P2 multi-step planning with dependent steps, P3 per-step self-verification with honest failure, P4 clarify-with-options, P5 two-layer thinking UX, P6 eval harness + hard cost ceiling. LangGraph plan-and-execute with hard caps (5 steps / 1 replan / 1 retry / token ceiling enforced at loop edges), all behind `PIPELINE_AGENTIC_ENABLED` with sandbox-first rollout. Zero new runtime dependencies.

### Domain Rules

- **Bounded cost (FR-019)**: Every question MUST run under hard limits: max steps, max retries, max plan revisions, and a processing-cost (token) ceiling. All loops MUST be bounded by at least one of these.
- **Rollout (FR-026)**: The agentic pipeline MUST ship behind an operator-controlled switch; default OFF; sandbox honors it first; widened only after eval gates pass.
- **Config values (data-model §6)** — verbatim defaults table:

| Key | Default | Notes |
|---|---|---|
| `PIPELINE_AGENTIC_ENABLED` | `false` | Rollout flag (R10); sandbox honors it first. |
| `AGENT_MAX_PLAN_STEPS` | `5` | Hard cap (R2). |
| `AGENT_MAX_PLAN_REVISIONS` | `1` | Hard cap. |
| `AGENT_MAX_STEP_RETRIES` | `1` | Hard cap. |
| `AGENT_TOKEN_CEILING_INPUT` / `_OUTPUT` | `30000` / `4000` | Seed values; replaced by p95 from eval runs (R9). |
| `AGENT_TURN_DEADLINE_SECS` | TBD at build | Wall-clock guard. `None` = disabled; set at rollout (HUMAN-GATE in Slice F). |

### API Context

Not applicable — config layer only.

### Gate Criteria

- [ ] All seven settings present with the exact defaults above.
- [ ] `AGENT_TURN_DEADLINE_SECS` is a nullable int defaulting to `None` (guard disabled until rollout).
- [ ] Every flag documented in `backend/.env.example`.
- [ ] No hardcoded values elsewhere — these are the single source of truth.

---

## 🎯 Objective

Add the agentic-pipeline configuration flags and hard caps to the central settings object so every downstream node/guard reads from one source of truth, defaulting to a fully disabled, conservatively-bounded posture.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/core/test_config_agentic.py` — asserts all seven settings exist with the documented default values and correct types.

### Files to Update (REQUIRED)

- `backend/src/core/config.py` — add the seven settings to the existing Pydantic `Settings` class (match the existing field style/casing in that file).
- `backend/.env.example` — document all seven with a short comment each and their default values.

### Code/Logic Requirements

- Add to the Pydantic settings model (Pydantic = registry `validation_approach`):
  - `PIPELINE_AGENTIC_ENABLED: bool = False`
  - `AGENT_MAX_PLAN_STEPS: int = 5`
  - `AGENT_MAX_PLAN_REVISIONS: int = 1`
  - `AGENT_MAX_STEP_RETRIES: int = 1`
  - `AGENT_TOKEN_CEILING_INPUT: int = 30000`
  - `AGENT_TOKEN_CEILING_OUTPUT: int = 4000`
  - `AGENT_TURN_DEADLINE_SECS: int | None = None`  (None = wall-clock guard disabled; concrete value set at rollout)
- Use SCREAMING_SNAKE_CASE constant names (registry convention).
- Read the existing `Settings` class first; mirror its field declaration idiom and any `Field(...)` description pattern already in use.
- Acceptance Criteria:
  - Importing settings with no env overrides yields exactly the defaults above.
  - `AGENT_TURN_DEADLINE_SECS` defaults to `None`.
  - All keys appear in `.env.example`.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → N/A (config only)
- [ ] API endpoint → N/A

### Shared (All Platforms)
- [x] **Environment var** → Added to `backend/.env.example`

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/core/test_config_agentic.py --no-cov -q
docker compose exec -T backend ruff check src/core/config.py
```
**Success Criteria**: pytest reports all tests `passed` (asserting the seven defaults + `None` deadline); ruff prints `All checks passed!`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified (.env.example updated)
- [ ] Integration verification passed
