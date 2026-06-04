# Task: T-037 - wire-us1-intent

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (FR-001..FR-005 integration)
**Requirement**: FR-001, FR-002, FR-003, FR-004, FR-005
**Platform**: both (backend + frontend) | **Subagents Enabled**: yes
**Dependencies**: [T-023-intent-api-endpoints](./T-023-intent-api-endpoints.md), [T-024-intent-prompt-wiring](./T-024-intent-prompt-wiring.md), [T-025-intent-review-ui](./T-025-intent-review-ui.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (request-session-bound in write paths — FX41) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic / Zod) |
| `api.versioning` | url (/api/v1/) |
| `frontend.data_fetching` | tanstack-query |
| `conventions.files` | snake_case (py) / kebab-case (Next.js) |
| `testing.integration_framework` | httpx |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Slice A (Source Intent) ends with a wiring + integration task that proves the full vertical slice connects end to end: backend routes are actually included in the API surface, the frontend API client exposes typed getIntent/putIntent/proposeIntent functions, TanStack hooks are connected, and the Settings tab renders the intent section. An integration test exercises GET → propose → PUT → capability-ramp against a real database.

### Domain Rules

- **No orphan code**: every new file from T-020..T-025 must be reachable from a real entry point. This task closes the wiring gaps.
- **FX41 request-session binding** preserved across the wired write paths.
- **Capability ramp end-to-end** (data-model §1): after propose, status is `ai_set` (out_of_scope advisory); after PUT save, status is `user_set` (out_of_scope hard-decline authority). The integration test asserts the ramp.

### API Context (the wired surface — VERBATIM intent)

```yaml
GET  /api/v1/sources/{source_id}/intent          → 200 SourceIntent
PUT  /api/v1/sources/{source_id}/intent          → 200 SourceIntent (intent_status → user_set)
POST /api/v1/sources/{source_id}/intent/propose  → 202 (sets ai_set on completion) | 409 in-flight
```
Frontend client (`frontend/src/lib/api/sources.ts`) must export: `getIntentApi(sourceId)`, `putIntentApi(sourceId, body)`, `proposeIntentApi(sourceId)` + the `SourceIntent` / `SourceIntentUpdate` TypeScript types — mirroring the existing `getSourceApi` / `updateSourceApi` idiom in that file.

### Gate Criteria

- [ ] Intent routes confirmed included in the sources router / `src/api/v1/router.py` (reachable, not just defined).
- [ ] `frontend/src/lib/api/sources.ts` exports getIntent/putIntent/proposeIntent + `SourceIntent`/`SourceIntentUpdate` types.
- [ ] TanStack Query hooks connected; Settings tab renders `IntentSection`.
- [ ] Integration test: full GET → propose → PUT → ramp flow against a real DB passes.

---

## 🎯 Objective

Close the Slice A wiring: confirm backend route inclusion, add the typed frontend API client functions + hooks, ensure the Settings tab renders the intent section, and prove the full GET → propose → PUT → capability-ramp flow with an integration test against a real database.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/integration/test_intent_api.py` — integration test (httpx + real DB) walking: GET initial (`pending_ai`/`ai_set`) → POST propose (202) → GET shows AI-proposed `ai_set` with example_questions/out_of_scope populated (purpose still admin-only/empty) → PUT save with a purpose → GET shows `user_set` and out_of_scope now carries hard-decline authority intent. Admin auth used; assert non-admin is 403 on at least one route.

### Files to Update (REQUIRED)

- `frontend/src/lib/api/sources.ts` — add `getIntentApi`, `putIntentApi`, `proposeIntentApi` and the `SourceIntent` / `SourceIntentUpdate` types (mirror `getSourceApi` / `updateSourceApi`).
- `frontend/src/features/sources/hooks/useSources.ts` (or a new `useIntent.ts` hook beside it) — TanStack Query `useQuery`/`useMutation` wrappers used by `IntentSection`.
- `backend/src/api/v1/router.py` (or the sources router) — confirm/ensure the three intent routes are included in the mounted API surface.
- `frontend/src/app/(admin)/admin/sources/[id]/page.tsx` — confirm `IntentSection` is rendered in the Settings tab (mounts the hooks).

### Code/Logic Requirements

- Frontend client functions follow the existing fetch/error-handling idiom in `sources.ts` (same base URL + error envelope handling as `getSourceApi`).
- Hooks: `useIntentQuery(sourceId)`, `usePutIntentMutation(sourceId)` (invalidates the intent query on success), `useProposeIntentMutation(sourceId)`.
- Acceptance Criteria:
  - Backend: hitting `GET /api/v1/sources/{id}/intent` via the integration client returns 200 (route is mounted).
  - The propose→PUT sequence drives `intent_status` from `ai_set` to `user_set` (ramp asserted).
  - `IntentSection` receives data through the new hooks (no direct fetch in the component).

## 🔌 Wiring Checklist

### Web
- [x] **Backend route** → intent routes included in `src/api/v1/router.py` / sources router
- [x] **Frontend page** → `IntentSection` rendered in Settings tab
- [x] **API endpoint** → `sources.ts` client funcs added; hooks call them
- [x] **Component** → `IntentSection` mounted by source detail page

### Shared (All Platforms)
- [x] **API client** → getIntent/putIntent/proposeIntent added to service layer

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/integration/test_intent_api.py --no-cov -q
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: the integration test reports `passed` for the full GET → propose → PUT → ramp flow (and the 403 non-admin assertion); `tsc --noEmit` exits 0, proving the new client functions/types type-check.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified (router include + client funcs + hooks + Settings mount)
- [ ] Integration verification passed
