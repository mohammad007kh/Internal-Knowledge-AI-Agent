# Phase 2 — Product Completion: Feature Dashboard

**Branch**: `003-phase2-completion` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

---

## Status Overview

| Phase | Status |
|---|---|
| 2A — Core Loop (P0) | Pending |
| 2B — Admin Experience (P1) | Pending |
| 2C — Polish (P2) | Pending |
| Final Integration Review | Pending |

---

## Task Index

### Phase 2A — Core Loop (P0)

| Task | Description | Status |
|---|---|---|
| [T-001](./tasks/T-001-alembic-migrations.md) | Alembic migrations 0017–0020 | Pending |
| [T-002](./tasks/T-002-source-inspection-endpoint.md) | Backend: POST /sources/inspect | Pending |
| [T-003](./tasks/T-003-presigned-upload-url.md) | Backend: POST /sources/upload-url (MinIO presigned PUT) | Pending |
| [T-004](./tasks/T-004-sources-structured-request.md) | Backend: Refactor POST /sources to structured body | Pending |
| [T-005](./tasks/T-005-chat-sse-streaming.md) | Backend: POST /chat/sessions/{id}/messages SSE stream | Pending |
| [T-006](./tasks/T-006-source-wizard-frontend.md) | Frontend: Source registration wizard (5 steps) | Pending |
| [T-007](./tasks/T-007-chat-sse-streaming-frontend.md) | Frontend: Chat SSE streaming + message thread | Pending |
| [T-008](./tasks/T-008-chat-citation-clarification-cards.md) | Frontend: Citation panel + clarification + guardrail cards | Pending |

### Phase 2B — Admin Experience (P1)

| Task | Description | Status |
|---|---|---|
| [T-009](./tasks/T-009-llm-settings-backend.md) | Backend: LLM settings CRUD + test endpoints | Pending |
| [T-010](./tasks/T-010-policy-backend.md) | Backend: Policy CRUD + versioning | Pending |
| [T-011](./tasks/T-011-guardrail-events-backend.md) | Backend: Guardrail events list + detail endpoints | Pending |
| [T-012](./tasks/T-012-invitation-management-backend.md) | Backend: Invitation list + cancel endpoints | Pending |
| [T-013](./tasks/T-013-users-me-enhancements.md) | Backend: GET/PATCH /users/me enhancements | Pending |
| [T-014](./tasks/T-014-source-stats-refresh-description.md) | Backend: Source stats + refresh-description endpoints | Pending |
| [T-015](./tasks/T-015-sources-list-page.md) | Frontend: Sources list — status badges, sync now | Pending |
| [T-016](./tasks/T-016-source-detail-page.md) | Frontend: Source detail page — 4 tabs | Pending |
| [T-017](./tasks/T-017-llm-settings-admin-page.md) | Frontend: LLM Settings admin page | Pending |
| [T-018](./tasks/T-018-policy-guardrail-events-page.md) | Frontend: Company Policy + guardrail events page | Pending |
| [T-019](./tasks/T-019-users-page.md) | Frontend: Users page — last login, access tab, invitations | Pending |
| [T-020](./tasks/T-020-navigation-completion.md) | Frontend: Admin + chat sidebars, navigation completion | Pending |

### Phase 2C — Polish (P2)

| Task | Description | Status |
|---|---|---|
| [T-021](./tasks/T-021-profile-page.md) | Frontend: Profile page (name, password, citation pref) | Pending |
| [T-022](./tasks/T-022-scheduled-syncs-celery.md) | Backend: check_scheduled_syncs Celery task | Pending |
| [T-023](./tasks/T-023-empty-states.md) | Frontend: Empty states for all list views | Pending |
| [T-024](./tasks/T-024-error-states.md) | Frontend: Error states + retry for all data-loading pages | Pending |
| [T-025](./tasks/T-025-network-offline-toast.md) | Frontend: Network offline toast notification | Pending |

### Final Review

| Task | Description | Status |
|---|---|---|
| [T-026](./tasks/T-026-integration-review.md) | Integration review — wiring, routing, button verification | Pending |

---

## Key Constraints (always in effect)

1. File bytes must never pass through the FastAPI backend (MinIO presigned PUT) — FR-006.
2. Every LLM call must be Langfuse-traced (Constitution §II) — FR-005, FR-021.
3. Celery Beat runs as a SINGLE REPLICA (`replicas: 1`) — no duplicate scheduled jobs (Constitution §V).
4. `connection_config` and `file_storage_path` must never appear in any API response.
5. Soft-delete only — never hard-delete sources, users, or sessions.

---

## Traceability

See [traceability.md](./traceability.md) for the full FR → Task → Commit SHA mapping.

---

## Completion Criteria

Phase 2 is complete when:
- All 26 tasks are marked `Completed`.
- T-026 integration review passes with zero gaps.
- `npx tsc --noEmit` passes with zero errors.
- `pytest` passes with zero failures.
- All 20 new API endpoints return correct responses.
