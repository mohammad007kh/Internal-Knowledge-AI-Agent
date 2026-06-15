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

## Known follow-ups (from the holistic review — tracked, not done)
- **a11y (MEDIUM)**: `DetailPanel` slide-over doesn't restore focus to the trigger on close, and doesn't trap focus / isn't `aria-modal`.
- **Parity (MEDIUM)**: the admin sandbox flattens clarification/guardrail to plain text instead of rendering `ClarificationCard`/`GuardrailCard`, so it can't preview the options UX.
- **Dedup (MEDIUM)**: the finished-turn footer (accordion + budget + affordance) and the in-flight bubble are duplicated across `MessageThread`/`TestTab` — extract `<AgenticTurnFooter>` (+ `<InFlightBubble>`). Keep the two stream hooks separate (they diverge on session lifecycle).
- **LOW**: `hadClarification` prop chain (PlanCard ← ActivityAccordion) is unreached — both call sites default `false`; wire it (needs cross-turn state) or remove. `BudgetFooter.costNote` now has no live caller. Pre-existing `PulsingDots` copies aren't `motion-reduce`-gated. `mode="review"` on the accordion is unreached until reload-restore exists.

## 004 status
Slices D + E code-complete + verified on both surfaces. Remaining are environment/
human-gated (eval-harness run, Playwright e2e, rollout gate) — see
`specs/004-agentic-pipeline/index.md` + `HANDOFF-sliceD.md`.
