# AGENTS.md — Frontend (Internal Knowledge AI Agent)

Scoped guide for agents working in `frontend/`. The repo-root `AGENTS.md` /
`CLAUDE.md` govern the whole project; this file adds frontend-specific rules and
documents the **004 agentic-pipeline transparency UI**. Keep it short and current.

## Stack
Next.js 15 (App Router) · React 19 · TypeScript 5.6 (strict) · Tailwind CSS v4 ·
shadcn/Radix · TanStack Query v5 · lucide-react · sonner.

## Non-negotiable conventions
- **Lint/format with Biome — NEVER eslint/prettier.** `pnpm exec biome check [--write] <paths>`.
- **Tests run on the HOST, not a container.** From `frontend/`:
  - unit: `pnpm exec vitest run <file>`
  - types: `pnpm exec tsc --noEmit`
  - lint: `pnpm lint` / `pnpm exec biome check <paths>`
  - If `node_modules/.bin` is empty: `pnpm install --frozen-lockfile` first.
  (The `internalknowledgeaiagent-frontend-1` container is a runtime image — no devDeps, source not live-mounted. Do not run FE tests there.)
- **No new runtime dependencies for 004** (and prefer not to in general — check what exists first; e.g. there is NO `tailwindcss-animate`, so animations use hand-rolled `@keyframes` in `app/globals.css`).
- **Immutability**: never mutate state/props; rebuild (`new Map(prev)`, `{...x}`, `.map`). Enforced in reducers/selectors/state updates.
- **Types**: explicit props interfaces; `type` for unions, `interface` for object shapes; avoid `any` (use `unknown` + narrow). Define icon props via the shared `IconGlyph` (`components/chat/types.ts`).

## Feature 004 — agentic transparency UI (shipped)

Surfaces the agent's plan-and-execute work in the chat. Backend streams SSE events;
the frontend folds them into a per-turn activity log and renders two layers.

### The event model is the single source of truth — `lib/sse/agent-events.ts`
- `parseAgentEvent(type, data)` — wire → typed `AgentEvent` (`plan`/`step`/`replan`/`budget`). **Defensive: never throws; unknown/terminal events → `null` (silent drop).**
- `activityLogReducer(state, event)` — **pure, immutable** fold into `ActivityState` (`activePlan`, `supersededPlan`, `replanReason`, `entries[]`).
- Selectors narrow state per component: `selectActiveStep`, `selectLatestBudget`, `selectStepStates`, `selectHasTrouble`, `selectStepRuns`. **Components call selectors — don't re-derive from `entries`.**
- Both stream hooks consume it in their `default:` SSE branch; the 4 intermediate events are **additive only** — they never set a terminal flag or touch `sawTerminal`. Terminal events stay exactly `done`/`error`/`clarification`/`guardrail_blocked`.

### Flag gate is TRANSITIVE — there is no frontend flag
Backend `PIPELINE_AGENTIC_ENABLED` off ⇒ no plan/step events ⇒ empty `activityLog`
⇒ the classic `PulsingDots` render + no accordion ⇒ **zero rendered change**. Gate
agentic UI on `activityLog.entries.length > 0`, never on a frontend env flag.
(Regression-tested in `MessageThread.test.tsx`.)

### Component map (`components/chat/`)
| Layer | Components |
|---|---|
| Primitives | `StepStatusBadge` (state→glyph), `agent-roles.ts` (`ROLE_ICON`/`ROLE_LABEL`), `OptionButtonGroup` (quick-reply buttons + free-text, `resetKey`) |
| Layer 1 (in-flight) | `StatusLine` — one mutating line, stable `aria-live`, ✓-flash, budget wrap-up |
| Layer 2 (finished turn) | `ActivityAccordion` (+ `RoleSection`/`Handoff`) — collapsed-by-default **native disclosure** (button + `hidden` region, NOT Radix), `PlanCard` (FR-008 visibility), `BudgetFooter` (quiet over-ceiling note), `ContinueSearchAffordance` (honest "Search again"/"Leave it here") |
| Slide-over | `CitationPanel` → `DetailPanel` (discriminated `PanelContent = {citation|step}`; thin `CitationPanel` wrapper kept for back-compat) |
| Clarify (US4) | `ClarificationCard` (calm, permitted-source options + free-text) |

### Wiring (two surfaces, same components)
- **Main chat**: `use-chat-stream.ts` → `useChat.ts` → `ChatLayout.tsx` → `MessageThread.tsx` (`MessageBubble`).
- **Admin sandbox**: `app/(admin)/admin/sources/[id]/_components/TestTab.tsx` via `useSandboxStream.ts`.
- **Per-turn persistence (T-072)**: `MessageThread` snapshots `activityLog` into a `Map<messageId, ActivityState>` keyed by the stream's `lastMessageId` (NOT the most-recent persisted id — that lags the refetch and mis-attributes). In-memory only → re-expand is **live-session-only**; reload starts empty.
- **The continue-flow only appears on the live edge**: most-recent assistant turn, `budget.offer_continue`, not dismissed, not streaming. "Search again" sends a static follow-up turn (`KEEP_SEARCHING_PROMPT`) — there is **no backend resume**.

### UX/a11y rules (calm-honesty design language)
- Tokens only: `text-muted-foreground` (floor), `bg-muted/40`, `border-border`, `text-amber-600 dark:text-amber-400` (trouble — never red), `text-emerald-600 dark:text-emerald-400` (✓). Always ship `dark:` pairs. No `text-[11px]`, no raw gray/white-alpha.
- **Color is never the only signal** — pair every state color with an `sr-only` token.
- Role identity = lucide icon; **color encodes STATE only**.
- Every animation `motion-safe:`-gated (or a `prefers-reduced-motion` media query). Touch targets `min-h-[44px]`.
- Render backend-controlled strings as React text children (auto-escaped). Never `dangerouslySetInnerHTML`.

### Security (Rule 2)
Clarification options are **server-clipped to the user's permitted sources** (backend T-080) and rendered verbatim. The chosen option id re-enters as a **normal turn** that the backend **re-authorizes** — an option id is NOT a capability token. Don't make the frontend decide offerability.

### Testing pattern
Fold typed `AgentEvent[]` fixtures through the **real** `activityLogReducer` (see the `fold()`/`foldFrames()` helpers); assert **DOM only** in component tests. Never hand-author `ActivityState`.

## Review fixes — expert-designed + supervisor-validated plan

A 4-team review + per-fix design teams + a supervisor validated the following.
**Sequencing (supervisor): A is independent; B/C/D are STRICTLY SERIAL `C → D → B`**
(all three edit `TestTab.tsx`; C/D both edit `MessageThread.tsx` — do NOT parallelize).

- **Fix A — DONE** (`4fe0f5b7`): `DetailPanel` restores focus to its trigger on close
  (WCAG 2.4.3), NON-modal (no trap/aria-modal — read alongside live chat). Type-guarded
  capture before moving focus.
- **Fix C (do FIRST) — extract `<AgenticTurnFooter>`** (`components/chat/`): stateless;
  folds the `entries.length>0` guard + `selectLatestBudget` + the 5-clause `showContinue`
  predicate; renders `ActivityAccordion(mode=live)` + `BudgetFooter` + gated
  `ContinueSearchAffordance`. Both `MessageBubble` + `SandboxBubble` render it; keep
  `continueDismissed`/`lastAssistantId` in each parent. **Supervisor correction: add a
  `messageId`/`turnId` prop** (needed for `continueDismissed.has(id)` + the continue/leave
  callbacks). Do NOT extract `<InFlightBubble>` (intentional MarkdownLite/testid divergence).
- **Fix D (do SECOND, on the slimmed call sites)**:
  - D1 DELETE `hadClarification` chain (PlanCard + ActivityAccordion) → `shouldRenderPlanCard(plan)` = `steps.length>=2 || revision>=1`. **Supervisor correction: first confirm every clarification path yields `≥2 steps || revision≥1`** (else a 1-step/no-revision clarification loses its plan card — keep a clause if so). Record the FR-008 intent in traceability.
  - D2 DELETE `BudgetFooter.costNote` prop + its test assertion (no live caller).
  - D3 FIX: add `motion-reduce:animate-none` to the `PulsingDots` in MessageThread + TestTab (+ test), matching StatusLine.
  - D4 DELETE `ActivityAccordion mode="review"` + its branch/test (supervisor ruling: no reload-restore roadmapped; snapshots are documented live-session-only — reintroduce with a real consumer when specced). Record in traceability.
- **Fix B (do LAST — HIGH) — sandbox clarification parity**: mirror the main hook in
  `useSandboxStream` (parse + expose `clarificationOptions`/`clarificationAllowFreeText`,
  reuse `StreamClarificationOption`); widen `SandboxMessage` with
  `clarification?:{question;options?;allowFreeText}`; capture it BEFORE `reset()` (mirror the
  `activity` capture); render the real `ClarificationCard` in `SandboxBubble`
  (`onReply→send`, `resetKey=message.id`). **Supervisor corrections: gate interactivity on
  `isLastAssistant && !isStreaming`** (not last alone — avoids a stale-but-interactive card
  during a following stream); **render non-last clarifications read-only**. Defer `GuardrailCard`
  (cosmetic, non-interactive). Rule 2 holds: the reply re-enters as a normal re-authorized turn.

Each fix lands as its own commit through the drill (TDD → code-reviewer + ui-ux/007 → green).

## 004 status
Slices D + E code-complete + verified on both surfaces. Remaining are environment/
human-gated (eval-harness run, Playwright e2e, rollout gate) — see
`specs/004-agentic-pipeline/index.md` + `HANDOFF-sliceD.md`.
