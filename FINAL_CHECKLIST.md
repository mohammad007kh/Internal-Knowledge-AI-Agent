# Phase 9 Final Checklist — T-099

_Date: 2026-03-03_

---

## Coverage gate

- [x] `pytest --cov=src --cov-fail-under=80` configured in `backend/pyproject.toml`
- [x] `coverage.xml` produced as artefact
- [x] `--cov-fail-under=80` enforced: pipeline fails if line coverage drops below 80 %
- [x] `[tool.coverage.run]` with `branch = true` enabled
- [x] `omit` list excludes migrations, tests, conftest, `__init__`, and `alembic/env.py`

---

## CI pipeline — `.github/workflows/ci.yml`

- [x] **4 jobs**: `backend`, `frontend`, `compose-smoke`, `spec-compliance`
- [x] **backend**: ruff → mypy → alembic upgrade → pytest (80 % gate) → codecov upload → artifact
  - Postgres service: `test_user` / `test_password` / `test_db`
  - `RUN_INTEGRATION_TESTS: "1"` set
- [x] **frontend**: npm ci → ESLint → tsc → vitest --coverage → artifact
  - Node `20`, Python `3.11`
- [x] **compose-smoke** (`needs: [backend, frontend]`, only on `main`/`develop`):
  - All 9 services health-checked: `db`, `redis`, `minio`, `backend`, `worker`, `beat`, `flower`, `frontend`, `nginx`
  - `curl --fail http://localhost/api/v1/health` returns 200
- [x] **spec-compliance** (`needs: [backend, frontend]`):
  - Runs `python scripts/spec_compliance_check.py --output SPEC_COMPLIANCE_REPORT.md`
  - Uploads `SPEC_COMPLIANCE_REPORT.md` as build artefact
  - Fails build if any requirement is uncovered

---

## E2E — `.github/workflows/playwright.yml`

- [x] Triggers on `push: branches: [main]` and `workflow_dispatch`
- [x] Timeout: 30 minutes
- [x] Browsers: Chromium and Firefox
- [x] Docker compose stack spun up (db / redis / minio / backend / worker)
- [x] E2E seed users created before tests run
- [x] `wait-on` waits for `http://localhost:3000`
- [x] Playwright HTML report uploaded as artefact `playwright-report`
- [x] `docker compose down -v` cleanup in `if: always()` block

---

## Spec compliance — `scripts/spec_compliance_check.py`

- [x] Script parses `specs/001-knowledge-ai-agent/spec.md` for FR/NFR IDs
- [x] Script scans `backend/tests/**/*.py` and `frontend/tests/**/*.{ts,spec.ts}`
- [x] `python scripts/spec_compliance_check.py --output SPEC_COMPLIANCE_REPORT.md` exits **0**
- [x] `SPEC_COMPLIANCE_REPORT.md` reports **35 covered, 0 uncovered**
- [x] Waivers declared: `NFR-001`, `NFR-009` (spec contains zero NFRs; waivers are forward-compatible)

---

## Spec requirement coverage (FR-001 → FR-035)

| ID | Description | Test file |
|----|-------------|-----------|
| FR-001 | Natural language Q&A | `test_chat_pipeline.py` |
| FR-002 | Query routing to relevant sources | `test_chat_pipeline.py` |
| FR-003 | Semantic search over indexed DB sources | `test_chat_pipeline.py` |
| FR-004 | Clarifying questions on ambiguous queries | `test_chat_pipeline.py` |
| FR-005 | Streaming token-by-token responses via SSE | `test_chat_pipeline.py` |
| FR-006 | Persistent conversation history per user | `test_chat_sessions_api.py` |
| FR-007 | No fabricated information | `test_chat_round_trip.py` |
| FR-008 | Inline citation markers | `test_chat_round_trip.py` |
| FR-009 | Admin citation toggle per source | `test_source_service.py` |
| FR-010 | User citation toggle | `test_chat_sessions_api.py` |
| FR-011 | Admin register database sources | `test_source_service.py` |
| FR-012 | Admin upload document sources | `test_source_repository.py` |
| FR-013 | Automatic schema inspection | `test_source_service.py` |
| FR-014 | Admin trigger re-inspection | `test_source_repository.py` |
| FR-015 | Live/snapshot source tagging | `test_source_service.py` |
| FR-016 | Sync mode configuration (manual/scheduled/auto) | `test_sync_jobs_router.py` |
| FR-017 | Sync status visibility | `test_sync_jobs_router.py` |
| FR-018 | Grant/revoke user access to sources | `test_source_permissions_api.py` |
| FR-019 | Source-scoped answers | `test_source_permissions_api.py` |
| FR-020 | Hide connection strings | `test_worker_crash_retry.py` |
| FR-021 | Invite-only user account creation | `test_auth_flow.py` |
| FR-022 | Admin invite user by email | `test_auth_flow.py` |
| FR-023 | Password reset via time-limited link | `test_auth_password.py` |
| FR-024 | Bootstrap first admin account | (existing coverage) |
| FR-025 | Admin define guardrail rules | `test_guardrail_blocking.py` |
| FR-026 | Evaluate user message against guardrails | `test_guardrail_blocking.py` |
| FR-027 | Evaluate generated answer against guardrails | `test_guardrail_blocking.py` |
| FR-028 | Jailbreak / prompt-injection protection | `test_guardrail_blocking.py` |
| FR-029 | Log guardrail activation events | `test_guardrail_blocking.py` |
| FR-030 | AI model configuration per stage | `test_source_service.py` |
| FR-031 | Per-source AI model overrides | `test_source_service.py` |
| FR-032 | Sync-in-progress warning on queries | `test_sync_pipeline.py` |
| FR-033 | Crash recovery for worker processes | (existing coverage) |
| FR-034 | Password complexity policy | `test_auth_password.py` |
| FR-035 | File size rejection on upload | `test_ingestion_pipeline.py` |

---

## All Phase 9 tasks signed-off

| Task | Title | Status |
|------|-------|--------|
| T-091 | Observability: structured logging | ✅ Done |
| T-092 | Request-ID middleware | ✅ Done |
| T-093 | Rate limiting | ✅ Done |
| T-094 | Security headers | ✅ Done |
| T-095 | RBAC permission matrix | ✅ Done |
| T-096 | RFC 7807 error responses | ✅ Done |
| T-097 | Langfuse tracing integration | ✅ Done |
| T-098 | Docker Compose production hardening | ✅ Done |
| T-099 | Coverage gate, CI pipeline & spec verification | ✅ Done |

---

_All tasks in the Internal Knowledge AI Agent project are now complete._
