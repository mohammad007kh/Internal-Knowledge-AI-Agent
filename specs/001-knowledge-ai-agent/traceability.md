# Traceability Matrix — Internal Knowledge AI Agent

## Overview

This document provides two cross-reference views of the 99-task specification:

1. **Task Dependency Matrix** — which tasks block or depend on which others (Format 2 and Format 4 tasks only; Format 1 and Format 3 files contain no structured dependency fields)
2. **Requirement Cross-Reference** — which tasks implement or reference each functional/non-functional requirement

---

## 1. Task Dependency Matrix

Only tasks with explicit dependency metadata are listed:
- **Format 2** (Markdown metadata table): T-006, T-011, T-025–T-039
- **Format 4** (bold inline fields): T-080–T-099

Format 1 tasks (T-001–T-005, T-007–T-010, T-012–T-024) and Format 3 tasks (T-040–T-079) contain no structured `Depends on` / `Blocks` fields and are excluded from this matrix.

### Format 2 — Auth & Foundation Tasks

| ID | Title | Depends On | Blocks |
|---|---|---|---|
| T-006 | Makefile targets (dev, test, lint, build, migrate) | T-001, T-002, T-003, T-004, T-005 | All subsequent tasks |
| T-011 | RFC 7807 Error Handler + FastAPI Exception Hierarchy | T-004 | T-025, T-026, T-053, T-064, T-070 |
| T-025 | Auth Service | T-012, T-013, T-022, T-023 | T-026, T-030, T-037 |
| T-026 | Auth FastAPI Router (7 endpoints) | T-015, T-016, T-017, T-024, T-025, T-027 | T-030, T-036, T-037 |
| T-027 | FastAPI Auth Dependencies (`get_current_user`, `require_role`) | T-012, T-023, T-025 | T-026, T-028, T-030, T-053, T-064, T-070 |
| T-028 | Users FastAPI Router (CRUD + Invitation) | T-015, T-023, T-024, T-027, T-029 | T-030, T-036 |
| T-029 | Email Service (Invitation + Password Reset) | T-004 | T-026, T-028, T-030 |
| T-030 | Frontend Auth Pages (Login, Setup, Password Reset) | T-005, T-026, T-031, T-032 | T-036, T-038 |
| T-031 | Frontend Auth TanStack Query Hooks | T-005, T-025, T-026, T-032 | T-030, T-033, T-038 |
| T-032 | Frontend Auth React Context (`useAuth`) | T-005, T-031 | T-030, T-033, T-038 |
| T-033 | Admin Users Page (Frontend) | T-028, T-031, T-032, T-038 | T-036, T-039 |
| T-034 | Change-Password Page (Frontend) | T-030, T-031, T-032 | T-036 |
| T-035 | Auth Integration Tests (Backend) | T-008, T-025, T-026, T-027, T-028, T-029 | T-039 |
| T-036 | Playwright E2E: Auth Flows | T-009, T-030, T-031, T-032, T-034, T-035 | T-039 |
| T-037 | Router Wiring and Container Registration (Phase 1 Completion) | T-004, T-015, T-019, T-022, T-023, T-024, T-025, T-026, T-027, T-028, T-029 | T-039 |
| T-038 | Next.js Middleware for Auth Route Protection | T-005, T-032 | T-033, T-039 |
| T-039 | Phase 1 Sign-Off Checklist | T-020, T-025, T-026, T-027, T-028, T-029, T-030, T-031, T-032, T-033, T-034, T-035, T-036, T-037, T-038 | T-040 |

### Format 4 — Chat Frontend, Admin Frontend & Testing Tasks

| ID | Title | Depends On | Blocks |
|---|---|---|---|
| T-080 | Chat UI Page — Split-Pane Layout | T-075, T-076 | T-081, T-082, T-086 |
| T-081 | Chat Input Bar & SSE Streaming | T-076, T-080 | T-086 |
| T-082 | Source Selector & Conversation Context UI | T-074, T-080 | T-086 |
| T-083 | Message Thread & Citation Viewer | T-074, T-080, T-081 | T-086 |
| T-084 | Session Management UI | T-076, T-080 | T-086 |
| T-085 | Feedback & Rating UI | T-076, T-083 | T-086 |
| T-086 | Chat E2E Playwright Tests | T-081, T-082, T-083, T-084, T-085 | T-090 |
| T-087 | Admin — Source & Connector Management UI | T-060, T-061, T-062, T-063, T-064, T-065, T-066, T-067, T-068, T-069, T-080 | T-090 |
| T-088 | Admin — User Management UI | T-050, T-080 | T-090 |
| T-089 | Admin — System Health & Analytics Dashboard | T-055, T-059, T-080 | T-090 |
| T-090 | Unit Tests — Services & Connectors | T-086, T-087, T-088, T-089 (all production code complete) | T-099 |
| T-091 | Integration Tests — API Flows | T-035, T-090 | T-099 |
| T-092 | Integration Tests — LangGraph Pipeline Nodes | T-070, T-071, T-072, T-090 | T-099 |
| T-093 | Playwright E2E Tests | T-080, T-081, T-082, T-083, T-084, T-085, T-086, T-087, T-088, T-089, T-091 | T-099 |
| T-094 | Accessibility Audit — WCAG-AA Compliance | T-080, T-081, T-082, T-083, T-084, T-085, T-086, T-087, T-088, T-089, T-093 | T-099 |
| T-095 | Integration Tests — Worker Crash & Retry (FR-033) | T-092 | T-099 |
| T-096 | Security Hardening — Headers, Rate Limiting & RBAC Smoke Tests | T-091 | T-099 |
| T-097 | Dark Mode, Responsive Layout & Polish | T-093, T-094 | T-099 |
| T-098 | Structured Logging, X-Request-ID Correlation & Langfuse Trace Verification | T-091 | T-099 |
| T-099 | Coverage Gate, CI Pipeline & Final Spec Verification | T-091, T-092, T-093, T-094, T-095, T-096, T-097, T-098 | — |

---

## 2. Requirement Cross-Reference

Requirements are sourced from the project specification. Each row lists every task file that explicitly references the given requirement ID in its body text.

No `SC-` (success criterion) tags were found in any task file; the table below covers all FR and NFR references discovered via full-corpus grep.

| Requirement | Description | Referenced In (Tasks) |
|---|---|---|
| FR-007 | LangGraph pipeline integration | T-092 |
| FR-019 | Source-scoped retrieval and permission enforcement | T-025, T-030, T-033, T-038, T-042, T-043, T-044, T-053, T-054, T-055, T-059, T-064, T-066, T-068, T-069, T-070, T-071, T-074, T-077, T-078, T-079 |
| FR-020 | RESTful API with RFC 7807 error responses | T-001, T-006, T-011, T-025, T-030, T-031, T-032, T-042, T-043, T-044, T-046, T-047, T-048, T-050, T-057, T-059, T-064, T-068, T-069, T-072, T-079 |
| FR-021 | Role-based access control (RBAC) | T-006, T-011, T-025, T-026, T-028, T-030, T-031, T-032, T-033, T-035, T-036, T-038, T-079 |
| FR-022 | Invitation-based user onboarding | T-028, T-079 |
| FR-023 | JWT access tokens + rotating httpOnly refresh cookies | T-025, T-026, T-079 |
| FR-024 | Bootstrap first admin from environment variables | T-006, T-011, T-020, T-025, T-026, T-037, T-059, T-079 |
| FR-025 | Password reset via email token | T-079 |
| FR-026 | Structured audit log for auth events | T-079 |
| FR-028 | Background sync jobs via Celery | T-090, T-091 |
| FR-030 | Text chunking and embedding pipeline | T-062, T-064, T-066, T-067, T-068, T-069 |
| FR-031 | pgvector similarity search | T-063, T-064, T-068, T-069 |
| FR-033 | Worker crash recovery and task retry | T-006, T-011, T-016, T-019, T-025, T-030, T-059, T-060, T-061, T-064, T-065, T-066, T-067, T-068, T-069, T-095 |
| FR-034 | Structured logging with X-Request-ID correlation | T-001, T-006, T-011, T-020, T-025, T-026, T-033, T-034, T-035, T-036, T-093 |
| FR-035 | Langfuse tracing integration | T-001, T-006, T-011, T-025, T-030, T-047, T-059, T-064, T-069, T-090, T-093 |
| NFR-001 | Availability / uptime target | T-099 (waiver — infrastructure concern outside task scope) |
| NFR-009 | Docker CPU/memory limits | T-099 (waiver — container runtime configuration, not application code) |

---

## 3. Coverage Notes

| Item | Value |
|---|---|
| Total tasks | 99 |
| Tasks with explicit dep metadata | 37 (T-006, T-011, T-025–T-039, T-080–T-099) |
| Tasks without dep metadata (Format 1 / Format 3) | 62 |
| Unique FR references found | 15 (FR-007, FR-019 through FR-026, FR-028, FR-030, FR-031, FR-033 through FR-035) |
| Unique NFR references found | 2 (NFR-001, NFR-009) |
| SC references found | 0 |
| Requirements with broadest task coverage | FR-019 (21 tasks), FR-020 (21 tasks), FR-033 (16 tasks) |
| Final gate task | T-099 — depends on all Phase 9 tasks; blocks nothing |

---

## 4. Implementation Status

| ID | Title | Status | Verified | Completed |
|---|---|---|---|---|
| T-001 | Project Scaffolding — Directory Structure, Tooling Configuration, and Monorepo Root | Done | Y | 2025-07-14 |
| T-002 | Docker Compose — 9-Service Stack | Done | Y | 2025-07-14 |
| T-003 | PostgreSQL + pgvector Init, Alembic Baseline Migration, and DB Healthcheck | Done | Y | 2025-07-14 |
| T-004 | FastAPI Application Factory, Dependency Injection Container, and Core Settings | Done | Y | 2025-07-14 |
| T-005 | Next.js 15 App Scaffold — App Router, shadcn/ui, Tailwind, TanStack Query Provider | Done | Y | 2026-02-26 |
| T-006 | Makefile targets (dev, test, lint, build, migrate) | Done | Y | 2026-02-26 |
| T-007 | GitHub Actions CI (lint → test → build) | Done | Y | 2026-02-26 |
| T-008 | pytest Foundation (async fixtures, test DB, HTTP client) | Done | Y | 2026-02-26 |
| T-009 | Playwright E2E Scaffold (smoke tests, CI workflow) | Done | Y | 2026-02-26 |
| T-010 | Structured Logging Middleware + X-Request-ID Correlation | Done | Y | 2026-02-26 |
| T-011 | RFC 7807 Error Handler + AppError Exception Hierarchy | Done | Y | 2026-02-26 |
| T-012 | JWT Utility — Access Token + Rotating httpOnly Refresh Cookie | Done | Y | 2026-02-26 |
