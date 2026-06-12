/**
 * Shared SSE agent-event model (T-070, US5 foundation).
 *
 * This module is the SINGLE source of truth for parsing and folding the four
 * INTERMEDIATE agentic SSE events (`plan`, `step`, `replan`, `budget`) into a
 * per-turn `activityLog`. Both stream hooks
 * (`src/hooks/use-chat-stream.ts` and the admin sandbox
 * `useSandboxStream.ts`) consume it so the event-handling logic lives in ONE
 * place instead of two duplicated switch statements.
 *
 * ## Intermediate vs. terminal (load-bearing — see contracts/sse-events.md)
 *
 * `plan` / `step` / `replan` / `budget` are ADDITIVE — they append/update the
 * `activityLog` and NEVER end the turn. The turn still terminates only on the
 * existing `done` / `error` / `clarification` / `guardrail_blocked` frames,
 * which the hooks handle themselves. This module deliberately exposes NO
 * terminal flag: the optimistic-bubble protection lives in the hooks
 * (their `sawTerminal` / `sawTerminalEvent` locals), not here.
 *
 * ## Wire (snake_case) → TS (camelCase) field mapping
 *
 * The mapping is mechanical — every wire field maps to exactly one TS field:
 *
 *   plan event
 *     revision          → revision
 *     reason            → reason
 *     steps[].id        → steps[].id
 *     steps[].label     → steps[].label
 *     steps[].source_id → steps[].sourceId
 *     steps[].source_name → steps[].sourceName
 *     steps[].depends_on  → steps[].dependsOn
 *
 *   step event
 *     step_id           → stepId
 *     role              → role
 *     state             → state
 *     label             → label
 *     summary           → summary
 *     progress.current  → progress.current
 *     progress.total    → progress.total
 *
 *   replan event
 *     reason                → reason
 *     superseded_revision   → supersededRevision
 *
 *   budget event
 *     ceiling_hit       → ceilingHit
 *     not_completed     → notCompleted
 *     offer_continue    → offerContinue
 *
 * Unknown event types are dropped silently (`parseAgentEvent` returns `null`)
 * and malformed payloads are tolerated defensively (never throw).
 */

// ---------------------------------------------------------------------------
// Discriminated-union event types (keyed on `type`)
// ---------------------------------------------------------------------------

/** Role that authored a step narration — drives per-role UI blocks. */
export type AgentRole = 'planner' | 'executor' | 'verifier' | 'synthesizer'

/** Lifecycle state of a plan step. */
export type StepState = 'started' | 'finished' | 'failed' | 'retrying'

/** Per-step progress counter carried on `step` events. */
export interface StepProgress {
  current: number
  total: number
}

/** One step in a plan (wire `steps[]`). */
export interface PlanStep {
  id: string
  label: string
  sourceId: string
  sourceName: string
  dependsOn: string[]
}

/** `plan` — the planner's step list. `revision` 0 = initial, 1 = revised. */
export interface PlanEvent {
  type: 'plan'
  revision: 0 | 1
  reason: string | null
  steps: PlanStep[]
}

/** `step` — narration for a single plan step (start/finish/fail/retry). */
export interface StepEvent {
  type: 'step'
  stepId: string
  role: AgentRole
  state: StepState
  label: string
  summary: string | null
  progress: StepProgress
}

/** `replan` — records why the plan changed and which revision it supersedes. */
export interface ReplanEvent {
  type: 'replan'
  reason: string
  supersededRevision: number
}

/** `budget` — emitted once if the agent hit its step/cost ceiling. */
export interface BudgetEvent {
  type: 'budget'
  ceilingHit: boolean
  notCompleted: string[]
  offerContinue: boolean
}

/**
 * The intermediate-event union this module parses & folds.
 *
 * NOTE: room is intentionally left for a future `clarification` structured
 * payload (`options[]`, T-080/T-081). That event is TERMINAL and is handled by
 * the hooks directly, so it is NOT parsed here — but the union name and the
 * `parseAgentEvent` silent-drop contract make adding it later non-breaking.
 */
export type AgentEvent = PlanEvent | StepEvent | ReplanEvent | BudgetEvent

// ---------------------------------------------------------------------------
// ActivityEntry — the per-turn narration log the later UI reads
// ---------------------------------------------------------------------------

/** A per-step / per-role narration entry derived from a `step` event. */
export interface StepActivityEntry {
  kind: 'step'
  stepId: string
  role: AgentRole
  state: StepState
  label: string
  summary: string | null
  progress: StepProgress
}

/** A plan snapshot entry (one per `plan` event, including revisions). */
export interface PlanActivityEntry {
  kind: 'plan'
  revision: 0 | 1
  reason: string | null
  steps: PlanStep[]
}

/** A replan note (one per `replan` event). The superseded plan is retained. */
export interface ReplanActivityEntry {
  kind: 'replan'
  reason: string
  supersededRevision: number
}

/** A budget note (one per `budget` event). Intermediate — never ends the turn. */
export interface BudgetActivityEntry {
  kind: 'budget'
  ceilingHit: boolean
  notCompleted: string[]
  offerContinue: boolean
}

/** Tagged union of everything the activity log can hold. */
export type ActivityEntry =
  | StepActivityEntry
  | PlanActivityEntry
  | ReplanActivityEntry
  | BudgetActivityEntry

/**
 * Per-turn activity state folded from the intermediate events.
 *
 * - `activePlan`     — the current plan (latest `plan` event wins).
 * - `supersededPlan` — the plan replaced by a replan; RETAINED so later UI can
 *                      inspect it (never discarded). Paired with `replanReason`.
 * - `entries`        — ordered narration log (steps appended/updated in place,
 *                      plan/replan/budget appended). The UI renders from this.
 */
export interface ActivityState {
  activePlan: PlanActivityEntry | null
  supersededPlan: PlanActivityEntry | null
  replanReason: string | null
  entries: ActivityEntry[]
}

/** The empty starting state for a fresh turn. */
export const emptyActivityState: ActivityState = {
  activePlan: null,
  supersededPlan: null,
  replanReason: null,
  entries: [],
}

// ---------------------------------------------------------------------------
// Defensive narrowing helpers (tolerate malformed wire data — never throw)
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function asBoolean(value: unknown): boolean {
  return value === true
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

const AGENT_ROLES: ReadonlySet<string> = new Set(['planner', 'executor', 'verifier', 'synthesizer'])

const STEP_STATES: ReadonlySet<string> = new Set(['started', 'finished', 'failed', 'retrying'])

function asRole(value: unknown): AgentRole {
  return AGENT_ROLES.has(value as string) ? (value as AgentRole) : 'executor'
}

function asStepState(value: unknown): StepState {
  return STEP_STATES.has(value as string) ? (value as StepState) : 'started'
}

function asRevision(value: unknown): 0 | 1 {
  return value === 1 ? 1 : 0
}

function parsePlanSteps(value: unknown): PlanStep[] {
  if (!Array.isArray(value)) return []
  const steps: PlanStep[] = []
  for (const raw of value) {
    if (!isRecord(raw)) continue
    steps.push({
      id: asString(raw.id),
      label: asString(raw.label),
      sourceId: asString(raw.source_id),
      sourceName: asString(raw.source_name),
      dependsOn: asStringArray(raw.depends_on),
    })
  }
  return steps
}

function parseProgress(value: unknown): StepProgress {
  if (!isRecord(value)) return { current: 0, total: 0 }
  return {
    current: asNumber(value.current),
    total: asNumber(value.total),
  }
}

// ---------------------------------------------------------------------------
// parseAgentEvent — wire (type, data) → typed AgentEvent | null
// ---------------------------------------------------------------------------

/**
 * Parse one intermediate agentic SSE frame into a typed `AgentEvent`.
 *
 * Returns `null` for unknown event types (SILENT drop — never throws) and
 * tolerates malformed `data` defensively (missing/wrong-typed fields fall back
 * to safe defaults rather than throwing). Terminal events (`done`, `error`,
 * `clarification`, `guardrail_blocked`) are NOT handled here — they return
 * `null` so the hooks keep their existing terminal handling unchanged.
 *
 * @param type  the SSE `event:` name
 * @param data  the already-JSON-parsed `data:` payload (may be malformed/unknown)
 */
export function parseAgentEvent(type: string, data: unknown): AgentEvent | null {
  switch (type) {
    case 'plan': {
      const d = isRecord(data) ? data : {}
      return {
        type: 'plan',
        revision: asRevision(d.revision),
        reason: asStringOrNull(d.reason),
        steps: parsePlanSteps(d.steps),
      }
    }
    case 'step': {
      const d = isRecord(data) ? data : {}
      return {
        type: 'step',
        stepId: asString(d.step_id),
        role: asRole(d.role),
        state: asStepState(d.state),
        label: asString(d.label),
        summary: asStringOrNull(d.summary),
        progress: parseProgress(d.progress),
      }
    }
    case 'replan': {
      const d = isRecord(data) ? data : {}
      return {
        type: 'replan',
        reason: asString(d.reason),
        supersededRevision: asNumber(d.superseded_revision),
      }
    }
    case 'budget': {
      const d = isRecord(data) ? data : {}
      return {
        type: 'budget',
        ceilingHit: asBoolean(d.ceiling_hit),
        notCompleted: asStringArray(d.not_completed),
        offerContinue: asBoolean(d.offer_continue),
      }
    }
    default:
      // Unknown / terminal / future event types — silent drop.
      return null
  }
}

// ---------------------------------------------------------------------------
// activityLogReducer — pure, immutable fold of events into activity state
// ---------------------------------------------------------------------------

/**
 * Fold one intermediate `AgentEvent` into the per-turn `ActivityState`.
 *
 * PURE and IMMUTABLE: returns a brand-new state object (and brand-new nested
 * arrays/objects) on every call — the input `state` is NEVER mutated. Intended
 * to be driven by the hooks' `setActivityLog((prev) => activityLogReducer(prev, event))`.
 *
 * Folding rules:
 *  - `plan`   → becomes the `activePlan`; appended to `entries`.
 *  - `step`   → updates the matching step entry IN A NEW ARRAY if one with the
 *               same `stepId` already exists, otherwise appends a new one
 *               (always-narrate: start then finish/fail/retry).
 *  - `replan` → records `supersededPlan` (the current `activePlan`, RETAINED)
 *               and `replanReason`; appends a replan entry. The following
 *               `plan` (revision 1) then becomes the new `activePlan`.
 *  - `budget` → appends a budget entry (intermediate — does NOT end the turn).
 *
 * No event here sets any terminal flag; intermediate events are additive only.
 */
export function activityLogReducer(state: ActivityState, event: AgentEvent): ActivityState {
  switch (event.type) {
    case 'plan': {
      const planEntry: PlanActivityEntry = {
        kind: 'plan',
        revision: event.revision,
        reason: event.reason,
        steps: event.steps.map((s) => ({ ...s, dependsOn: [...s.dependsOn] })),
      }
      return {
        ...state,
        activePlan: planEntry,
        entries: [...state.entries, planEntry],
      }
    }
    case 'step': {
      const stepEntry: StepActivityEntry = {
        kind: 'step',
        stepId: event.stepId,
        role: event.role,
        state: event.state,
        label: event.label,
        summary: event.summary,
        progress: { ...event.progress },
      }
      const existingIndex = state.entries.findIndex(
        (e) => e.kind === 'step' && e.stepId === event.stepId
      )
      if (existingIndex === -1) {
        return { ...state, entries: [...state.entries, stepEntry] }
      }
      const nextEntries = state.entries.map((e, i) => (i === existingIndex ? stepEntry : e))
      return { ...state, entries: nextEntries }
    }
    case 'replan': {
      const replanEntry: ReplanActivityEntry = {
        kind: 'replan',
        reason: event.reason,
        supersededRevision: event.supersededRevision,
      }
      return {
        ...state,
        // Retain the plan being superseded so later UI can inspect it.
        supersededPlan: state.activePlan,
        replanReason: event.reason,
        entries: [...state.entries, replanEntry],
      }
    }
    case 'budget': {
      const budgetEntry: BudgetActivityEntry = {
        kind: 'budget',
        ceilingHit: event.ceilingHit,
        notCompleted: [...event.notCompleted],
        offerContinue: event.offerContinue,
      }
      return { ...state, entries: [...state.entries, budgetEntry] }
    }
    default:
      // Exhaustive over AgentEvent; unreachable. Return state unchanged.
      return state
  }
}
