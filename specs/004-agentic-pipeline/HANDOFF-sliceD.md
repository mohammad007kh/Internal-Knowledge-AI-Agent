# HANDOFF — Slice D (frontend) + remainder of 004-agentic-pipeline

> Written at the 26/41 milestone so a FRESH session resumes with zero re-derivation
> (Context Pinning). Synthesized from a 3-expert panel (frontend / UX / architecture)
> + supervisor ruling. Read this + `index.md` + the relevant task file + `traceability.md`.

## Status: 26/41 done, all committed, full unit suite green (~1838)

**Backend is COMPLETE + verified.** Slice C (T-050→T-059) + Slice E backend (T-080) done.
The agentic graph plans → executes → verifies (light + heavy SQL) → replans → synthesizes,
budget-guarded at loop edges, behind `PIPELINE_AGENTIC_ENABLED` (sandbox-first), guardrails
wrapping unconditionally, emitting SSE `plan`/`step`/`budget`/`replan`/`clarification`/`done(activity_summary)`.
Backend↔frontend wire seam verified consistent against `contracts/sse-events.md`.

Also done this session (beyond roadmap): credential-leak class fixed (canonical `redact_dsn`),
non-DSN secret sweep (clean), 19 pre-existing test failures fixed.

Slice D foundation **T-070 done**: `frontend/src/lib/sse/agent-events.ts` (discriminated-union
event types + pure `activityLogReducer` + `parseAgentEvent`) wired into BOTH stream hooks.

## What remains
- **Slice D UI**: T-071 status line, T-072 summary chip + persistence, T-073 activity accordion + plan card, T-074 budget footer, T-075 honest-failure UI + OptionButtonGroup, T-077 wire (sandbox-first → main chat).
- **Slice E UI**: T-081 ClarificationCard (reuse OptionButtonGroup), T-082 wire.
- **Slice F**: T-090 eval gate calibration (needs real harness runs), **T-091 ⚠️ HUMAN-GATE** (rollout deadline + flag widening — cannot be auto-completed), T-092 constitution Art. IV amendment, T-093 final e2e (Playwright) + ACCEPTANCE.md.
- **Deferred (separate issues, NOT in 004 chain)**: Dockerfile spaCy/libxcb gap (structure-aware parser never runs in prod; only the fallbacks do).

## Supervisor-ruled execution order
1. **Fresh session #1 (UI, serial — do NOT parallelize; shared-primitive coupling):**
   primitives + fixtures FIRST → T-071 → **T-073 (defines the shared primitives)** → T-072 → T-074 → T-075 → then **T-077 LAST**.
2. **Fresh session #1 cont. / #2:** T-081 (ClarificationCard, reuses OptionButtonGroup) → T-082 wire.
3. **Fresh session #3 (close-out):** kick off T-090 eval runs EARLY (long pole, parallel) → T-092 → finalize T-090 → T-093 + ACCEPTANCE.md → **T-091 human gate LAST**.

## TESTING (critical — see CLAUDE.md "Testing & Verification")
- **Frontend tests run on the HOST**, not a container: from `frontend/` → `pnpm exec vitest run <file>`, `pnpm exec tsc --noEmit`, `pnpm lint` (Biome — NEVER eslint). If `node_modules/.bin` is empty, `pnpm install --frozen-lockfile` first.
- Backend tests: in the `internalknowledgeaiagent-backend-1` container, source NOT live-mounted → `docker cp backend/src/. ...:/app/src/` + `docker cp backend/tests/. ...:/app/tests/` (WHOLE dirs) before pytest.

## Shared-primitive contract (build ONCE, under `frontend/src/components/agent/`)
Captured here so the fresh session doesn't re-derive or duplicate:
- `StepStatusBadge` — step status → lucide icon + color token. (T-073 + T-072)
- `ActivityEntry` — renders one reduced activity-log entry (role/label/state). (T-071 latest-only; T-073 full list)
- `PlanCard` — step list + dependency order + StepStatusBadge. (T-073; T-072 reuses read-only)
- `RoleSection` — Radix Accordion.Item per role. (T-073)
- `OptionButtonGroup` — quick-reply buttons `{id,label,value}[]` + `onSelect`. **Built in T-075, REUSED by T-081 ClarificationCard — design the prop contract to serve both.**

## Component architecture (load-bearing)
- Components are **prop-driven on `activityLog`** (from T-070's reducer). The hook→props **adapter lives ONLY at the 2 surfaces** (`use-chat-stream.ts` main, `useSandboxStream.ts` sandbox). This makes every component trivially testable AND makes T-077 a one-line integration per surface.
- **Test via scripted event-sequence FIXTURES folded through the REAL `activityLogReducer`** (no live backend). Create `frontend/src/lib/sse/__fixtures__/agent-events.fixtures.ts`: happyPath / replan / budget / abstain / clarification sequences as typed `AgentEvent[]`. Derive expected `activityLog` by folding fixtures through the real reducer — never hand-author reducer output.

## Hard UX constraints (UX expert — the feature succeeds/fails on these)
- **Default-collapsed is sacred** (Layer 2 accordion ships closed).
- **ONE mutating status line, never a stacking log** (Layer 1 mutates in place). Encode a test that the status line is a single replaced node, not an append.
- Calm present-tense language; no internal jargon.
- Motion < 200ms ease-out + honor `prefers-reduced-motion` (kills all motion).
- **A11y**: status line `aria-live="polite" aria-atomic="true"` on a stable container (stop announcing at terminal); accordion = real disclosure semantics (Radix) + keyboard + visible focus; option buttons = real `<button>`s.
- **Dark mode via tokens** (muted "quiet" text must stay legible in BOTH themes — the #1 silent-failure spot).
- Budget/cost = a footnote (tertiary, no red/amber unless actually over).
- Internal flag-gated tool → invest in **behavior + a11y**, coast on decoration. Trim: T-072 persistence = **in-memory per-turn only** (no localStorage). No e2e in Slice D (that's T-093).

## UX review cadence (no designer in the loop every step)
Build sandbox-first → per visual component run `/design-review` (slop/spacing/hierarchy) → drive a MOCK event stream through the sandbox with the browser tool and screenshot each phase (idle / planning / executing / done-with-chip / failure × light/dark) → ONE human gate at the end (light/dark side-by-side + reduced-motion + keyboard-only walkthrough).

## Confirmed facts (don't re-investigate)
- `activityLog` is ALREADY in `use-chat-stream.ts` (T-070) → **T-077 must NOT edit the stream hook**; it's pure consumption. Editing it is a smell.
- Migration `0037_message_activity` (chat_messages.activity_summary JSONB) is present → T-072 persistence dep satisfied.
- The 4 intermediate events (plan/step/replan/budget) are additive — they must NEVER set a terminal flag / `messageType` / `lastMessageId`, and must NOT be added to the `sawTerminal`/`sawTerminalEvent` set (still exactly clarification/guardrail_blocked/done/error in both hooks).
- Wire shapes (verified): `plan{revision,reason,steps[{id,label,source_id,source_name,depends_on}]}`, `step{step_id,role,state,label,summary,progress{current,total}}`, `budget{ceiling_hit,not_completed,offer_continue}`, `replan{reason,superseded_revision}`, `clarification{question,options?[{id,label,hint?,recommended?}],allow_free_text}`, `done.activity_summary` (data-model §3). `ChatStreamEvent.plan/step/budget/replan/clarification` factories in `backend/src/schemas/chat.py` now match these.

## T-077 (under-scoped in roadmap — split explicitly)
(a) reuse the sandbox wire; (b) verify flag gating; (c) **flag-OFF regression**: prove ZERO rendered change at the main-chat surface when the flag is disabled (this is the real acceptance bar; the roadmap doesn't name it).

## T-091 human gate (decision package, decide LAST)
Everything else can merge "dark" behind the default-off flag. Tee up a one-page rollout brief: current flag state, proposed widening (sandbox → internal → % main-chat), the **T-090 eval evidence** (p95 + success criteria), rollback = flip flag off, proposed deadline. T-090 → T-091 is producer→consumer (bind them). Draft ACCEPTANCE.md's 8 criteria UP FRONT as the build checklist.

## Open follow-ups (tracked, separate)
- Dockerfile spaCy/libxcb gap (prod parity for the structure-aware doc parser).
