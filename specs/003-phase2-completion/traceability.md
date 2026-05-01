# Traceability Matrix: Phase 2 — Product Completion

Maps every functional requirement to the task(s) that implement it and the commit that closes it.

| Req ID | Requirement Summary | Task(s) | Commit SHA |
|--------|---------------------|---------|------------|
| FR-001 | Alembic migrations: source_mode, retrieval_mode, description, sync fields, status | T-001 | _TBD_ |
| FR-002 | Source model extended: source_mode, sync_mode, sync_schedule, citations_enabled | T-001, T-004 | _TBD_ |
| FR-003 | Source registration wizard — 5 steps, file upload via presigned URL | T-006 | _TBD_ |
| FR-004 | Source inspection: AI-generated description on connection | T-002 | _TBD_ |
| FR-005 | All LLM calls Langfuse-traced | T-002, T-005, T-009 | _TBD_ |
| FR-006 | File bytes never pass through backend — MinIO presigned PUT | T-003, T-006 | _TBD_ |
| FR-007 | POST /sources accepts structured body (not raw JSON blob) | T-004 | _TBD_ |
| FR-008 | Source wizard: description editable before saving | T-006 | _TBD_ |
| FR-009 | Sources list: status badge, document count, last synced, sync now | T-015 | _TBD_ |
| FR-010 | Sources list: search and filter by type and status | T-015 | _TBD_ |
| FR-011 | Source detail page with 4 tabs: Overview, Sync, Access, Settings | T-016 | _TBD_ |
| FR-012 | Source detail: view stats (document_count, chunk_count, sync_job_count) | T-014, T-016 | _TBD_ |
| FR-013 | Source detail: refresh AI description without saving | T-014, T-016 | _TBD_ |
| FR-014 | Chat message submission returns SSE stream | T-005, T-007 | _TBD_ |
| FR-015 | SSE tokens stream in real time to frontend | T-005, T-007 | _TBD_ |
| FR-016 | Citations surfaced in chat response | T-005, T-007, T-008 | _TBD_ |
| FR-017 | Clarification card rendered when AI requests clarification | T-005, T-007, T-008 | _TBD_ |
| FR-018 | Guardrail blocked card rendered when message is blocked | T-005, T-007, T-008 | _TBD_ |
| FR-019 | Partial message persisted when client aborts stream | T-005 | _TBD_ |
| FR-020 | Chat session: create, rename, delete (soft) | T-005, T-020 | _TBD_ |
| FR-021 | Admin: view LLM settings per pipeline stage | T-009, T-017 | _TBD_ |
| FR-022 | Admin: edit LLM settings per stage (provider, model, key, temp, tokens) | T-009, T-017 | _TBD_ |
| FR-023 | Admin: save LLM settings | T-009, T-017 | _TBD_ |
| FR-024 | Admin: test LLM connection — verify key + model works | T-009, T-017 | _TBD_ |
| FR-025 | Admin: view current company policy | T-010, T-018 | _TBD_ |
| FR-026 | Admin: edit and save company policy (versioned) | T-010, T-018 | _TBD_ |
| FR-027 | Admin: list guardrail events (paginated, filterable) | T-011, T-018 | _TBD_ |
| FR-028 | Admin: view guardrail event detail with original input | T-011, T-018 | _TBD_ |
| FR-029 | Users list: last login column | T-019 | _TBD_ |
| FR-030 | Users: source access tab — per-user source permissions | T-019 | _TBD_ |
| FR-031 | Admin: list pending invitations + cancel (revoke) | T-012, T-019 | _TBD_ |
| FR-032 | User: view own profile (name, email, role, citation preference) | T-013, T-021 | _TBD_ |
| FR-033 | User: update display name and citation preference | T-013, T-021 | _TBD_ |
| FR-034 | User: change password (requires current password verification) | T-013, T-021 | _TBD_ |
| FR-035 | Admin sidebar: all admin pages linked | T-020 | _TBD_ |
| FR-036 | Chat sidebar: New Chat, session list, profile link | T-020 | _TBD_ |
| FR-037 | Active link highlighting in both sidebars | T-020 | _TBD_ |
| FR-038 | Celery Beat task fires every 60 seconds | T-022 | _TBD_ |
| FR-039 | next_sync_due_at computed from cron expression | T-022 | _TBD_ |
| FR-040 | Sync dispatched for sources with next_sync_due_at <= NOW() | T-022 | _TBD_ |
| FR-041 | Empty states on all list views | T-023 | _TBD_ |
| FR-042 | Error states with retry button on all data-loading pages | T-024 | _TBD_ |
| FR-043 | Network offline/online toast notification | T-025 | _TBD_ |

---

## Cross-Cutting Concerns

| Concern | Tasks | Notes |
|---|---|---|
| Langfuse tracing on all LLM calls | T-002, T-005, T-009 | Constitution §II — non-negotiable |
| MinIO presigned PUT (no file bytes through backend) | T-003, T-006 | Constitution §VI |
| Celery Beat single replica | T-022 | Constitution §V — `replicas: 1` always |
| connection_config never in API response | T-004, T-014 | Security — enforced in all serializers |
| Soft-delete only | T-012, T-020 | `deleted_at` column, never hard DELETE |
| RFC 7807 error format | T-002–T-014 | Registry standard for all backend errors |
| RBAC enforcement | T-002–T-014 | `require_admin` / `get_current_user` on every route |

---

## Update Instructions

When a task is completed, update its row with the merge commit SHA:

```
| FR-001 | ... | T-001 | abc1234 |
```

When all rows have a commit SHA, Phase 2 is fully traced and closed.
