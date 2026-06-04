# Task: T-023 - intent-api-endpoints

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (record + propose source intent)
**Requirement**: FR-001, FR-002 + Security rule 3
**Platform**: web | **Subagents Enabled**: yes
**Dependencies**: [T-020-intent-model-and-repo](./T-020-intent-model-and-repo.md), [T-021-intent-sanitization](./T-021-intent-sanitization.md), [T-022-intent-proposal-task](./T-022-intent-proposal-task.md)

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
| `api.versioning` | url (/api/v1/) |
| `api.error_format` | rfc7807 |
| `api.resource_naming` | plural |
| `api.auth_header` | bearer (JWT) |
| `backend.auth_pattern` | rbac (admin \| user) |
| `conventions.files` | snake_case (Python modules) |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Source intent is read and edited by admins through three endpoints; saving constitutes review (status → `user_set`, activating out-of-scope decline authority), and a propose endpoint (re)triggers the AI draft. These are admin-only mutations using the FX41 request-session binding pattern.

### Domain Rules — SECURITY RULE 3 (Intent API hardening, MEDIUM) — VERBATIM, embed as acceptance criteria

> `require_admin` dependency on all three endpoints (decorator-level, not documentation); request-session binding per the FX41 pattern; TOCTOU conditional UPDATE in the proposal task.

FX41 pattern (from recent commits): bind permission + connector write paths to the **request session** — construct repositories from `Depends(get_db)` in the route, do NOT resolve services from the DI container in write paths. PUT commits its transaction.

### API Context (from contracts/intent-api.yaml — VERBATIM intent)

```yaml
GET  /api/v1/sources/{source_id}/intent          → 200 SourceIntent | 404 Problem   (admin-only)
PUT  /api/v1/sources/{source_id}/intent          → 200 SourceIntent | 404 | 422 Problem  (admin-only)
     # Saving = review: intent_status → user_set; out_of_scope gains hard-decline authority (FR-005).
     # Validation: purpose <= 500 chars; example_questions <= 5; out_of_scope <= 10.
POST /api/v1/sources/{source_id}/intent/propose  → 202 queued | 404 | 409 (study/proposal in flight)  (admin-only)
     # BUNDLE-level; runs only while intent_status != user_set; conditional UPDATE; NEVER writes purpose/cross_source_hints.
```

`SourceIntentUpdate` (PUT body): all fields optional; provided fields replace stored values — `purpose` (≤500), `example_questions` (≤5), `out_of_scope` (≤10), `cross_source_hints`. Errors are RFC7807 `application/problem+json`.

### Gate Criteria

- [ ] `require_admin` dependency on EVERY route decorator (GET, PUT, POST-propose) — at decorator level, not just docs.
- [ ] Repos constructed from `Depends(get_db)` (request-session binding); no service resolution from the DI container in the write paths (FX41).
- [ ] PUT commits; PUT applies sanitization (T-021) → 422 on instruction-like/cap violation.
- [ ] POST-propose enqueues `tasks.propose_intent` → 202; returns 409 when a study/proposal is already in flight.
- [ ] RFC7807 problem responses on 404/422/409.

---

## 🎯 Objective

Add three admin-only `/api/v1/sources/{id}/intent` endpoints (GET, PUT, POST propose) using request-session-bound repos, PUT-time sanitization (422), and 202/409 propose semantics.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/schemas/source_intent.py` — Pydantic `SourceIntent` (response) and `SourceIntentUpdate` (request) mirroring the contract; field validators reuse `intent_sanitizer` (T-021) so instruction-like/cap violations raise → 422.
- `backend/tests/unit/api/test_intent_api.py` — unit API tests: 403 for non-admin, 422 for sanitization/cap violation, 200 happy path (status flips to `user_set`), 202 on propose, 409 when propose conflicts.

### Files to Update (REQUIRED)

- `backend/src/api/v1/sources.py` — add the three routes with `require_admin` on each; construct `SourceRepository` from `Depends(get_db)`; PUT calls `update_intent` and commits; propose enqueues `tasks.propose_intent` (409 if a study/proposal already in flight — reuse existing in-flight detection used by re-study).
- (If sources are split across an admin router) ensure the routes live on the existing sources router that is already included in `src/api/v1/router.py` (final inclusion confirmed in T-037).

### Code/Logic Requirements

- Decorator-level admin guard: `dependencies=[Depends(require_admin)]` (or the project's exact admin dependency) on each route — verified by a 403 test for a non-admin token.
- GET → `repo.get_intent(...)` → `SourceIntent`; 404 (RFC7807) when source missing.
- PUT → validate body (sanitizer in schema validators) → `repo.update_intent(...)` → `await session.commit()` → return updated `SourceIntent` with `intent_status == 'user_set'`. 422 (RFC7807) on validation failure.
- POST propose → if a study/proposal is already in flight → 409 (RFC7807); else `current_app.send_task("tasks.propose_intent", args=[str(source_id)])` → 202.
- Acceptance Criteria (security rule 3, embedded):
  - Non-admin token → 403 on all three.
  - Repos are request-session bound (constructed in the route from `Depends(get_db)`), not pulled from the container.
  - PUT with `purpose` starting `"You are"` → 422.
  - Propose → 202; concurrent in-flight → 409.

## 🔌 Wiring Checklist

### Web
- [x] **Backend route** → three routes added to the sources router (router inclusion confirmed in T-037)
- [x] **API endpoint** → frontend client wires to these in T-025/T-037

### Shared (All Platforms)
- [x] **Service registration** → propose route dispatches `tasks.propose_intent`

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/api/test_intent_api.py --no-cov -q
docker compose exec -T backend ruff check src/api/v1/sources.py src/schemas/source_intent.py
docker compose exec -T backend mypy src/api/v1/sources.py
```
**Success Criteria**: pytest reports `passed` for the 403 / 422 / 200(→user_set) / 202 / 409 cases; ruff `All checks passed!`; mypy `Success: no issues found`.

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
