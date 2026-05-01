# Project Defaults Changelog

This file tracks ALL changes to `registry.yaml`. Every update requires Human-In-The-Loop (HITL) approval and must be logged here with full context.

**Format**: Each entry documents what changed, when, why, and who approved it.

---

## Change Log

### 2026-04-21 | backend.sse_pattern
- **Changed**: `null` → `fastapi_streaming_response`
- **Why**: Phase 2 chat interface requires real-time token streaming. FastAPI `StreamingResponse` with `text/event-stream` + browser `fetch()` + `ReadableStream` chosen over EventSource (allows POST, custom headers).
- **Source**: specs/003-phase2-completion/plan.md
- **Approved by**: Human (accept)

### 2026-04-21 | backend.beat_pattern
- **Changed**: `null` → `polling_task_60s`
- **Why**: Phase 2 connector scheduling requires dynamic per-source cron schedules. Built-in polling task (60s interval, reads `sources` table) preferred over `celery-sqlalchemy-scheduler` v0.3.0 (low maturity). No new dependency needed.
- **Source**: specs/003-phase2-completion/plan.md
- **Approved by**: Human (accept)

<!--
Template for new entries (copy and fill):

### YYYY-MM-DD | [key.path]
- **Changed**: `[old_value]` → `[new_value]`
- **Why**: [Reason for the change]
- **Source**: [Which spec/phase triggered this decision]
- **Approved by**: Human ([accept | custom: "reason"])

-->

### 2026-02-25 | Initial Registry Seeding (all keys)
- **Changed**: All keys `null` → values derived from `docs/PRD.md` v0.6 and `specs/001-knowledge-ai-agent/spec.md`
- **Why**: First-time project registry population. All decisions were already locked in the PRD (6 revision cycles) and clarified in the spec (/speckit.clarify session). Seeding avoids re-asking settled questions in every downstream plan/task phase.
- **Source**: `docs/PRD.md` v0.6 + `specs/001-knowledge-ai-agent/spec.md` (post-clarify)
- **Approved by**: Human (accept — user confirmed "Yes, populate both now" in /speckit.plan initial config)

**Keys set in this entry**:
| Key | Value |
|-----|-------|
| architecture.pattern | modular_monolith |
| architecture.layers | clean |
| architecture.api_style | rest |
| architecture.communication | hybrid |
| architecture.repo_structure | monorepo |
| code_patterns.data_access | repository |
| code_patterns.dependency_injection | container |
| code_patterns.error_handling | exceptions |
| code_patterns.async_pattern | async_await |
| code_patterns.validation_approach | schema |
| code_patterns.null_handling | nullable |
| api.versioning | url |
| api.pagination | offset |
| api.error_format | rfc7807 |
| api.rate_limiting | none |
| api.idempotency | optional |
| api.resource_naming | plural |
| api.request_format | json |
| api.auth_header | bearer |
| api.response_envelope | wrapped |
| api.date_format | iso8601 |
| backend.language | python |
| backend.runtime_version | python:3.12 |
| backend.framework | fastapi |
| backend.orm | sqlalchemy |
| backend.auth_method | jwt |
| backend.auth_pattern | rbac |
| backend.job_queue | celery |
| backend.cache | redis |
| frontend.framework | nextjs |
| frontend.rendering | hybrid |
| frontend.ui_library | shadcn |
| frontend.styling | tailwind |
| frontend.state_management | context |
| frontend.data_fetching | tanstack-query |
| frontend.form_library | react-hook-form |
| frontend.validation_library | zod |
| frontend.routing | next-router |
| database.type | postgresql |
| database.tenancy_model | single_tenant |
| database.soft_delete | true |
| database.audit_columns | true |
| database.migration_strategy | versioned |
| database.connection_pooling | orm_default |
| database.query_style | raw_allowed |
| database.naming_tables | snake_case |
| database.naming_columns | snake_case |
| database.primary_key_type | uuid |
| error_handling.logging_format | structured |
| error_handling.log_level | info |
| error_handling.error_tracking | none |
| error_handling.tracing | none |
| error_handling.correlation_header | X-Request-ID |
| testing.unit_framework | pytest |
| testing.integration_framework | httpx |
| testing.e2e_framework | playwright |
| testing.coverage_target | 80 |
| testing.test_organization | separate |
| testing.mocking | manual |
| infrastructure.ci_cd | github-actions |
| infrastructure.container | docker |
| infrastructure.orchestration | docker-compose |
| infrastructure.cloud_provider | none |
| infrastructure.deployment_strategy | recreate |
| infrastructure.iac | none |
| infrastructure.secrets | env-files |
| conventions.variables | snake_case |
| conventions.files | snake_case |
| conventions.classes | PascalCase |
| conventions.constants | SCREAMING_SNAKE_CASE |
| conventions.commits | conventional |
| conventions.branches | NNN-description |
| conventions.pr_titles | conventional |
| ui_specs.dark_mode | true |
| ui_specs.responsive | true |
| ui_specs.accessibility | wcag-aa |
| ui_specs.animations | none |
| ui_specs.design_tokens | none |
| ui_specs.icons | lucide |
| ui_specs.notifications | sonner |
| security.cors | strict |
| security.csrf | samesite |
| security.csp | moderate |
| security.rate_limit_scope | ip |
| security.input_sanitization | strict |
| security.password_policy | moderate |

---

## How to Read This Log

| Field | Description |
|-------|-------------|
| **Date** | When the change was approved |
| **Key** | The registry.yaml path (e.g., `api.versioning`) |
| **Changed** | Old value → New value |
| **Why** | Business or technical rationale |
| **Source** | The spec, plan, or phase where decision was made |
| **Approved by** | Always "Human" + approval type |

## Approval Types

- `accept` - User approved the suggested value as-is
- `custom: "[text]"` - User provided a custom value or modified suggestion
- `reject` - User rejected adding this to defaults (kept as feature-specific)

---

## Deviation Log

When a spec deviates from registry defaults, it should be logged here for visibility.

<!--
Template for deviation entries:

### YYYY-MM-DD | Deviation in [feature-name]
- **Key**: [key.path]
- **Registry default**: [default_value]
- **Spec uses**: [different_value]
- **Reason**: [Why this spec needs different behavior]
- **Approved by**: Human

-->

*No deviations recorded yet.*
