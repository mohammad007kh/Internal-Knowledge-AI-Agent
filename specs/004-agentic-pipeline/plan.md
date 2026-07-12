# Implementation Plan: Transparent Multi-Step Agent (Agentic Pipeline)

**Branch**: `004-agentic-pipeline` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-agentic-pipeline/spec.md`

## Planning Configuration

**Configured At**: 2026-06-04
**Detected Platform**: web

| Setting | Value |
|---------|-------|
| Platform | Web |
| Subagents | Enabled |
| Available Subagents | ai-engineer, prompt-engineer, backend-architect, api-documenter, data-architecture, sql-pro, database-optimizer, frontend-developer, ui-ux-designer, python-pro, typescript-pro, ml-engineer, architect-reviewer, code-reviewer (mobile/* tree excluded — Platform=Web; payment/business/devops agents unmatched) |
| Competitive Analysis | No |
| Review Depth | Full |

**Subagent Details** (matched by semantic similarity to spec keywords):
- [x] ai-engineer — planner/executor/verify graph, RAG orchestration (STRONG)
- [x] prompt-engineer — planner/grader/judge/synthesizer prompts (STRONG)
- [x] backend-architect — intent API, SSE grammar, repositories (STRONG)
- [x] frontend-developer + ui-ux-designer — activityLog, two-layer UX (STRONG)
- [x] python-pro / typescript-pro — implementation idiom (STRONG)
- [x] sql-pro + database-optimizer — heavy SQL verification, migrations (MODERATE)
- [x] ml-engineer — eval harness, LLM-judge (MODERATE)
- [x] architect-reviewer + code-reviewer — post-slice review drill (STANDING)

## Summary

Evolve the linear retrieve-then-answer pipeline into a transparent
plan-and-execute agent. Six prioritized stories (spec): P1 source intent
metadata (hybrid authoring, capability-ramp authority), P2 multi-step
planning with dependent steps, P3 per-step self-verification with honest
failure, P4 clarify-with-options, P5 two-layer thinking UX, P6 eval harness
+ hard cost ceiling. Technical approach consolidated in
[research.md](./research.md) (R1-R11): LangGraph plan-and-execute with hard
caps (5 steps / 1 replan / 1 retry / token ceiling enforced at loop edges),
light+heavy-DB verification via a new `retrieval_grader` slot, two new SSE
events (`plan`, `step`) on the existing wire grammar, JSON-golden eval
harness in `backend/evals/`, all behind `PIPELINE_AGENTIC_ENABLED` with
sandbox-first rollout. Zero new runtime dependencies.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.6 (frontend)
**Primary Dependencies**: FastAPI, LangChain+LangGraph (existing pins), SQLAlchemy 2 async, Next.js 15, shadcn/ui, TanStack Query v5 — NO new runtime dependencies
**Storage**: PostgreSQL 16 + pgvector (2 expand-only migrations: source-intent columns, message activity_summary JSONB); Redis (unchanged); MinIO (unchanged)
**Testing**: pytest (80% gate) + httpx integration; Vitest + Playwright frontend; NEW: eval harness (JSON-golden + LLM-judge) in `backend/evals/`
**Target Platform**: Web (self-hosted Docker Compose, 9 services — unchanged)
**Project Type**: web (existing backend/ + frontend/ monorepo)
**Performance Goals**: first visible progress ≤2s (SC-003); status update at every step boundary; sandbox-first so live users see no regression until gates pass
**Constraints**: hard per-turn caps — ≤5 steps, ≤1 replan, ≤1 retry/step, token ceiling seed 30k in/4k out (p95-measured later); 100% bounded termination (SC-004); per-source permissions re-clipped at every plan step (FR-009)
**Scale/Scope**: single-tenant self-hosted; ~25 FRs; touches agent graph, 2 migrations, 2 new LLM slots, 4 SSE events, chat UI state model, eval harness

### Station gate notes (Stations 06/07/08/12/13)

- **06 API Contracts**: delta OpenAPI in `contracts/intent-api.yaml`; RFC7807
  errors (registry); SSE grammar contract in `contracts/sse-events.md`;
  mutations are admin-only PUT/POST with idempotent semantics (PUT replaces;
  propose is queue-once with 409 on conflict). ✅
- **07 Data Architecture**: single-tenant (registry); expand-only migrations
  documented in `data-model.md` §8; no naked queries — repository pattern +
  request-session binding (FX41 lesson encoded). ✅
- **08 Auth & RBAC**: no auth changes; existing admin/user roles; permission
  matrix unchanged — the NEW rule is plan-step permission re-clipping
  (FR-009), enforced server-side in planner + executor. ✅
- **12 CI/CD**: existing envs unchanged; release = flag-gated (FR-026);
  nightly eval job cloned from spec-compliance job shape; migrations run on
  startup per existing pattern. ✅
- **13 Security**: threat deltas — prompt content from intent fields is
  admin-authored (trusted tier) but AI-proposed text is model output: cap
  lengths + render as data, never as instructions; SQL verification reuses
  read-only + sqlglot hardening; no new external calls; budget guard caps
  cost-abuse. Rate limiting already shipped (registry corrected). ✅

## Tech Stack Approval

| Decision          | Value | Source   | Approved |
|-------------------|-------|----------|----------|
| Language/Version  | Python 3.12 / TS 5.6 | Registry/Constitution | [x] |
| Primary Framework | FastAPI · LangGraph · Next.js 15 | Registry/Constitution | [x] |
| Storage           | PostgreSQL 16 + pgvector · Redis · MinIO | Registry/Constitution | [x] |
| ORM/Data Layer    | SQLAlchemy 2 async + Alembic | Registry | [x] |
| Testing Framework | pytest · httpx · Vitest · Playwright | Registry | [x] |
| Target Platform   | Web (Docker Compose self-hosted) | Phase 0.1 / Spec | [x] |

**Assumptions Made**: none at tech-stack level — every row traces to
registry/constitution; feature-internal additions (LLM slots, SSE events,
flags, columns) are design artifacts, not stack decisions.

**Approval Status**: Approved
**Approved By**: Owner ("Approve all")
**Approved At**: 2026-06-04
**Revisions**: none

## Coding Standards

### Naming Conventions

| Context | Convention | Example |
|---------|------------|---------|
| Variables / Functions | snake_case (Python) | `intent_status`, `load_intent_block()` |
| Classes | PascalCase | `PlanStep`, `RetrievalGrader` |
| Constants | SCREAMING_SNAKE_CASE | `AGENT_MAX_PLAN_STEPS` |
| Files (components) | PascalCase .tsx | `PlanCard.tsx`, `ActivityAccordion.tsx` |
| Files (utilities/python) | kebab-case / snake_case | `use-activity-log.ts`, `budget_guard.py` |
| Database tables/columns | snake_case | `activity_summary`, `intent_status` |
| API endpoints | kebab-case plural | `/api/v1/sources/{id}/intent` |
| Environment vars | SCREAMING_SNAKE_CASE | `PIPELINE_AGENTIC_ENABLED` |

### Tooling

| Tool | Configuration | Command |
|------|---------------|---------|
| Linter (be) | ruff (pyproject.toml) | `ruff check src` |
| Types (be) | mypy strict (pyproject.toml) | `mypy src` |
| Lint/format (fe) | Biome (biome.json) | `pnpm lint` |
| Types (fe) | tsc (tsconfig.json) | `pnpm exec tsc --noEmit` |

### Agreed Standards

- **Style**: PEP 8 + project CLAUDE.md conventions; registry conventions confirmed current (drift review found zero convention drift)
- **Pre-commit Hooks**: No (CI-enforced)
- **Enforced in CI**: Yes (ruff, mypy, Biome, tsc, pytest 80% gate, Vitest)

**Standards Approved By**: Owner ("Keep them" + drift review performed)
**Standards Approved At**: 2026-06-04

## Tech Stack Validation

**Validation Date**: 2026-06-04
**Validation Status**: PASS

### Validation Results

| Package | Proposed | Validated | Status | Notes |
|---------|----------|-----------|--------|-------|
| FastAPI | existing pin | 0.136.3 available | PASS | No upgrade required by this feature |
| (new packages) | — | — | PASS | Feature introduces ZERO new runtime dependencies |

### Warnings

None. (Script artifact note: an initial run against the unfilled template
parsed placeholder text — `[e.g.` / `UIKit` — as package names; documented
here and disregarded. No real warnings exist.)

### User Overrides

None required.

**Validation Approval**: Approved (auto — PASS, no warnings; HITL #2 skip rule)
**Validated At**: 2026-06-04

## Frontend/UI Specifications

**UI Specifications Status**: Approved

### Core UI Stack

| Setting          | Value                          | Notes                |
|------------------|--------------------------------|----------------------|
| UI Library       | shadcn/ui (+ Radix)            | Registry             |
| Design System    | shadcn defaults + CSS variables | Registry (design_tokens: none) |
| State Management | React Context + TanStack Query v5 | Registry; NEW per-turn `activityLog: ActivityEntry[]` (intermediate-event class) |
| Form Handling    | React Hook Form + Zod          | Registry             |

### UI Features

| Feature              | Enabled | Implementation Notes            |
|----------------------|---------|---------------------------------|
| Dark Mode            | [x]     | next-themes (existing)          |
| Responsive/Mobile    | [x]     | Status line truncates; accordion full-width; slide-over → full-width on mobile |
| Accessibility (WCAG) | [x]     | AA (registry); OptionButtonGroup: roving focus + number keys + 44px targets; axe tests |
| Animations           | [x]     | minimal (registry, updated): CSS-only 200ms ease expand, fade+slide-in 8px |

### Component Standards

| Standard              | Rule                                         |
|-----------------------|----------------------------------------------|
| Component naming      | PascalCase                                   |
| File structure        | Feature folders (existing chat/ + features/) |
| Props interface       | Named TypeScript interface                   |
| Styling approach      | Tailwind v4                                  |
| Test file location    | __tests__ folders (existing convention)      |

### Additional UI Requirements (adopted §3D.1 design pass)

- Two-layer thinking UX: Layer 1 status line INSIDE the in-flight turn
  (replaces pulsing dots); Layer 2 collapsed-by-default inline accordion —
  NOT the CitationPanel slide-over for the live tree (slide-over reserved
  for post-hoc per-step payload inspection).
- Per-role blocks: lucide icons for role identity (Compass/FileText/
  Database/ShieldCheck/PenLine); color expresses STATE only (amber
  retry/fail); handoff connector line + transient `A → B` micro-label;
  amber dot bubbles to collapsed header on trouble.
- Plan card: fallback `bg-muted/40` styling; numbered list with ✓ ↻ ○ ✗
  ticks; rendered only for ≥2-step plans or post-revision/clarification.
- Replan: one-line "Plan updated — reason" note; superseded plan collapses
  (`▸ Original plan (superseded)`); NO strikethrough diff.
- Post-answer: summary chip in message meta row (`✓ Used 4 steps · 2
  sources · view activity`; amber variant on retry/failure); re-expands
  accordion in review mode; compact persistence only.
- Shared `OptionButtonGroup` primitive (clarify options + abstain
  quick-replies): vertical stack, hints, optional `Suggested` pill (never
  auto-selected), selection echoes as a user message.
- Honest-failure turn: extends dimmed-italic fallback styling + SearchX
  icon + thin amber left border; collapsible "What I tried" with SQL behind
  nested toggle.
- Budget-hit: slim neutral-amber footer banner inside the answer bubble
  (persists in history) + optional "Keep going" quick-reply (new turn).
- Cost note: plain-language size leading ("This was a medium question"),
  token count as dimmed suffix, panel-only; NO meters/counters/$.
- Staging: all of the above ships in the admin Test tab first (FR-026).

### UI Specifications Approval

**Approved By**: Owner ("Approve all")
**Approved At**: 2026-06-04
**Revisions**: none

## Constitution Check

_GATE: passed pre-research; re-checked post-Phase-1._

| Principle | Status | Note |
|---|---|---|
| I. Interface-First | ✅ | New services (planner, grader, intent proposal) behind Protocols, IoC-wired; repos request-session-bound (FX41 lesson) |
| II. LLM Observability | ✅ | Planner, grader, judge calls all Langfuse-traced with stage names; `turn_token_cost` score added |
| III. Connector Isolation | ✅ | No connector changes; verification consumes connector OUTPUT only |
| IV. Pipeline Safety | ✅ with note | New graph remains THE single answer path; guardrail input/output wrap it unconditionally; reflector untouched & default-OFF. NOTE: constitution's descriptive "8-node pipeline" wording becomes stale — text refresh via amendment process at feature completion (research.md R11) |
| V. Simplicity & YAGNI | ✅ | Deferred: trajectory evals, tiered budgets, advisory countdown, Retriever Protocol, MCP, editable plans, mid-flight asks |
| VI. Security by Default | ✅ | No auth changes; intent fields length-capped + rendered as data; SQL read-only hardening reused; plan-step permission re-clipping (FR-009) |

**Complexity Tracking**: no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/004-agentic-pipeline/
├── spec.md              # ✅ (/atomicspec.specify + clarify)
├── plan.md              # ✅ this file
├── research.md          # ✅ R1-R11
├── data-model.md        # ✅ entities + migrations
├── quickstart.md        # ✅ acceptance walkthrough
├── contracts/
│   ├── intent-api.yaml  # ✅ OpenAPI delta
│   └── sse-events.md    # ✅ wire grammar contract
├── checklists/requirements.md  # ✅ all-pass
│   (next: /atomicspec.tasks creates index.md, traceability.md, tasks/)
```

### Source Code (repository root — existing monorepo, touched areas)

```text
backend/
├── src/
│   ├── agent/
│   │   ├── pipeline.py          # new agentic graph builder (flag-selected)
│   │   ├── state.py             # raw_user_intent, plan, past_steps, budgets
│   │   └── nodes/               # NEW: planner.py, executor.py (or executor logic
│   │                            #   in retrieve/text_to_query reuse), verify.py,
│   │                            #   replan.py, budget_guard.py (edge guard fn),
│   │                            #   diagnostics injector; EXTEND: clarify options
│   ├── api/v1/sources.py        # intent GET/PUT/propose endpoints
│   ├── models/source.py         # intent columns; chat_message.activity_summary
│   ├── repositories/            # intent fields in source repo; message activity
│   ├── services/                # intent proposal task service; stage seeds
│   ├── schemas/chat.py          # plan/step/replan/budget events; clarification options
│   ├── tasks/                   # intent-proposal celery task (study-adjacent)
│   └── prompts/                 # planner.v1.txt, retrieval_grader.v1.txt, judge.v1.txt
├── evals/                       # NEW: cases/, fixtures/, run.py, compare.py, judge prompt
├── alembic/versions/            # 0036_source_intent, 0037_message_activity
└── tests/{unit,integration}/    # per-node units; graph integration; eval-runner tests

frontend/
└── src/
    ├── components/chat/         # StatusLine, ActivityAccordion, PlanCard,
    │   │                        #   OptionButtonGroup, BudgetFooter; MessageThread
    │   │                        #   integration; ClarificationCard options ext.
    │   └── useChat.ts / use-chat-stream.ts   # activityLog array; intermediate-event class
    ├── features/sources/        # Intent section in source Settings (review UI)
    └── app/(admin)/.../TestTab  # sandbox staging of the full UX (ships first)
```

**Structure Decision**: existing web monorepo (backend/ + frontend/);
feature is additive within established layers — no new top-level projects.
The only new directory is `backend/evals/` (eval harness, per R8).

## Phase 1 Design Summary

- **Data model**: [data-model.md](./data-model.md) — sources intent columns
  (tri-state capability ramp), chat_messages.activity_summary JSONB, agent
  state extensions, file-based eval cases, config flags, 2 expand-only
  migrations.
- **Contracts**: [contracts/intent-api.yaml](./contracts/intent-api.yaml)
  (GET/PUT intent + POST propose), [contracts/sse-events.md](./contracts/sse-events.md)
  (`plan`/`step`/`replan`/`budget` + extended `clarification`/`done`;
  ordering + compatibility rules).
- **Quickstart**: [quickstart.md](./quickstart.md) — flag-on walkthrough
  covering all six stories + eval gates.

## Delivery Sequencing (input to /atomicspec.tasks)

_Revised after the 3-expert plan review (2026-06-04): Slice C split into
C0-C8 atomic sub-slices (review blocker B1); eval baseline partitioned;
both SSE consumers named; security rules added below._

1. **Slice A — Source Intent (Story 1, P1)**: migration 0036 → intent
   proposal task (bundle-level semantics, conditional-UPDATE TOCTOU guard)
   → prompt wiring across ALL THREE description/intent consumers (pinned
   schema chunk, source_router catalog, text_to_query sketch — note: the
   `description` COLUMN exists; the gap is prompt injection-points, not a
   missing field) → intent API (with `require_admin` dependency on all 3
   endpoints) → admin review UI. Independently shippable; no flag needed.
2. **Slice B — Eval harness MVP (Story 6a)**: cases + fixtures loader
   (ephemeral schema seeding; synthetic-only data) + runner + judge +
   **partitioned baseline run**: current pipeline scored ONLY on
   single-source + honesty subsets (judge accepts implicit declines for
   baseline); multi-step cases authored now, first executed in Slice C/F.
3. **Slice C — Agentic graph (Stories 2+3, split atomic)**:
   - **C0** Token accumulation prerequisite: additive reducers on the token
     state fields; every LLM node (enumerated in R2) returns usage deltas;
     synthesizer estimate-then-reconcile. Independently testable.
   - **C1** State schema: PlanStep/StepResult types (incl. `bound_inputs`),
     `raw_user_intent`, plan/past_steps/current_step/plan_revision.
   - **C2** Planner node + `plan` SSE event (+ pre-emission permission
     assertion — see security rules).
   - **C3** Executor: per-step scratch (single source_id, resolved
     sub_query via R1b interpolation, step-scoped schema chunk), calls
     retrieval primitives as functions (the v2 `text_to_query →
     retrieve_context` fixed edge does NOT carry over), writes
     `StepResult.output_chunks` + `step` events.
   - **C4** Verify node — light grader (new `retrieval_grader` slot) +
     R4b state-machine edges.
   - **C5** Heavy SQL verification (deterministic db_safety gate + LLM
     judge on resolved sub_query + rows).
   - **C6** Replan node + `replan` event (reason carried; caps enforced).
   - **C7** budget_guard edge function + `budget` event + diagnostics
     injector + honest-failure synthesis path.
   - **C8** `PIPELINE_AGENTIC_ENABLED` flag in `build_pipeline()` selector
     + sandbox wiring + `done` event extension (NOTE: three code sites —
     `DoneData` schema, `ChatStreamEvent.done()` factory, and the
     `chat_stream_service` emission call).
4. **Slice D — Transparency UX (Story 5)**: activityLog state model
   (intermediate-event class) → StatusLine → summary chip →
   ActivityAccordion/PlanCard → slide-over payload inspection (ownership-
   checked endpoint). **Both SSE consumers are in scope** —
   `useSandboxStream.ts` (PRIMARY — sandbox ships first) and
   `use-chat-stream.ts`; extract shared event-handling into one module to
   end the parser duplication.
5. **Slice E — Clarify-with-options (Story 4)**: planner trigger + extended
   event + ClarificationCard options + OptionButtonGroup (shared with
   abstain quick-replies) — again BOTH stream hooks. Options generated only
   from the user's permitted source set.
6. **Slice F — Gates & rollout (Story 6b)**: eval gate run (SC-002/004/005,
   exit-code contract in quickstart §7) → cost-ceiling p95 calibration →
   set `AGENT_TURN_DEADLINE_SECS` (HUMAN-GATE checklist item, not an atomic
   code task: operator picks the value from observed eval-run durations;
   must be concrete before any flag widening) → flag widening decision
   (HUMAN-GATE) → **constitution text amendment** (stale "8-node pipeline"
   wording; tracked task, standard amendment process).

### Security rules for task generation (from the security plan-review)

Encode each as explicit acceptance criteria in the relevant task files:

1. **Intent prompt hygiene (HIGH)**: intent fields render inside
   unambiguous delimiters; treated as data, never instructions; write-time
   sanitization (PUT 422 + proposal-task output validation) against
   instruction-like leading patterns; proposal task never writes `purpose`
   or `cross_source_hints`.
2. **Permission assertions on new surfaces (HIGH)**: server asserts
   `plan.steps[].source_id ⊆ requesting user's permitted set` BEFORE
   emitting the `plan` event (LLM hallucination guard); clarification
   options generated only from the permitted set; `cross_source_hints`
   rendering checks the hinted source against the user's set — if
   inaccessible, say "another source may have this information" WITHOUT
   naming it; slide-over step-payload endpoint enforces session ownership.
3. **Intent API hardening (MEDIUM)**: `require_admin` dependency on all
   three endpoints (decorator-level, not documentation); request-session
   binding per the FX41 pattern; TOCTOU conditional UPDATE in the proposal
   task.
4. **Eval data hygiene (MEDIUM)**: fixtures synthetic-only (no real names/
   PII/business data — the repo is PUBLIC); required `"data_source":
   "synthetic"` field on every case, checked in CI; human review gate
   before committing fixtures.
5. **Stream/persistence hygiene (MEDIUM)**: `step.summary` is generated
   narration (first-3 + count), never raw row slices; `activity_summary`
   size-guarded at DB level (migration 0037 CHECK) + 200-char line caps in
   code.
6. **DoS posture (LOW, recommendation)**: optional
   `AGENT_MAX_CONCURRENT_TURNS_PER_USER` (default 2, Redis semaphore) —
   nice-to-have for v1, documented for operators.

Standing drill per slice: tests → code-review (+ security-review where
auth/SQL/permissions touched) → commit; expert second-opinion on any
non-trivial design pivot discovered during implementation.
