/**
 * Tests for the shared agentic SSE event model (T-070).
 *
 * Covers:
 *  - a scripted intermediate-event sequence (initial plan → step started →
 *    step finished → replan → revised plan(rev1) → budget) folds to the
 *    expected `activityLog` state;
 *  - `parseAgentEvent` returns `null` for unknown types (silent drop);
 *  - the reducer is a no-op for events outside its union (same-shaped state);
 *  - malformed `data` never throws;
 *  - NO terminal flag is set by any of the four intermediate events
 *    (the ActivityState type has no terminal field — the turn ends only on
 *    the hooks' own done/error/clarification/guardrail handling);
 *  - the superseded plan is RETAINED after a replan.
 */
import { describe, expect, it } from 'vitest'
import {
  type ActivityState,
  type AgentEvent,
  activityLogReducer,
  emptyActivityState,
  parseAgentEvent,
} from '../agent-events'

// ---------------------------------------------------------------------------
// parseAgentEvent — wire → typed event
// ---------------------------------------------------------------------------

describe('parseAgentEvent — snake_case → camelCase mapping', () => {
  it('parses a plan event, mapping source_id/source_name/depends_on', () => {
    const ev = parseAgentEvent('plan', {
      revision: 0,
      reason: null,
      steps: [
        {
          id: 's1',
          label: 'Read names from users.csv',
          source_id: 'uuid-1',
          source_name: 'users.csv',
          depends_on: [],
        },
      ],
    })
    expect(ev).toEqual({
      type: 'plan',
      revision: 0,
      reason: null,
      steps: [
        {
          id: 's1',
          label: 'Read names from users.csv',
          sourceId: 'uuid-1',
          sourceName: 'users.csv',
          dependsOn: [],
        },
      ],
    })
  })

  it('parses a step event, mapping step_id/progress', () => {
    const ev = parseAgentEvent('step', {
      step_id: 's1',
      role: 'executor',
      state: 'started',
      label: 'Reading users.csv…',
      summary: null,
      progress: { current: 1, total: 4 },
    })
    expect(ev).toEqual({
      type: 'step',
      stepId: 's1',
      role: 'executor',
      state: 'started',
      label: 'Reading users.csv…',
      summary: null,
      progress: { current: 1, total: 4 },
    })
  })

  it('parses a replan event, mapping superseded_revision', () => {
    const ev = parseAgentEvent('replan', {
      reason: 'CRM returned emails; switching to email match',
      superseded_revision: 0,
    })
    expect(ev).toEqual({
      type: 'replan',
      reason: 'CRM returned emails; switching to email match',
      supersededRevision: 0,
    })
  })

  it('parses a budget event, mapping ceiling_hit/not_completed/offer_continue', () => {
    const ev = parseAgentEvent('budget', {
      ceiling_hit: true,
      not_completed: ['Verify rows match the names', 'Write the full answer'],
      offer_continue: true,
    })
    expect(ev).toEqual({
      type: 'budget',
      ceilingHit: true,
      notCompleted: ['Verify rows match the names', 'Write the full answer'],
      offerContinue: true,
    })
  })

  it('returns null for unknown event types (silent drop)', () => {
    expect(parseAgentEvent('delta', { token: 'hi' })).toBeNull()
    expect(parseAgentEvent('done', { message_id: 'm1' })).toBeNull()
    expect(parseAgentEvent('clarification', { question: 'which?' })).toBeNull()
    expect(parseAgentEvent('totally_unknown', {})).toBeNull()
  })
})

describe('parseAgentEvent — malformed data tolerance (never throws)', () => {
  it('tolerates null/undefined/non-object data', () => {
    expect(() => parseAgentEvent('plan', null)).not.toThrow()
    expect(() => parseAgentEvent('step', undefined)).not.toThrow()
    expect(() => parseAgentEvent('budget', 'not-an-object')).not.toThrow()
    expect(() => parseAgentEvent('replan', 42)).not.toThrow()
  })

  it('falls back to safe defaults when fields are missing or wrong-typed', () => {
    const plan = parseAgentEvent('plan', { revision: 'bogus', steps: 'nope' })
    expect(plan).toEqual({ type: 'plan', revision: 0, reason: null, steps: [] })

    const step = parseAgentEvent('step', { role: 'martian', state: 'exploded' })
    expect(step).toEqual({
      type: 'step',
      stepId: '',
      role: 'executor', // unknown role → safe default
      state: 'started', // unknown state → safe default
      label: '',
      summary: null,
      progress: { current: 0, total: 0 },
    })

    const budget = parseAgentEvent('budget', {})
    expect(budget).toEqual({
      type: 'budget',
      ceilingHit: false,
      notCompleted: [],
      offerContinue: false,
    })
  })

  it('drops non-string entries from plan depends_on / budget not_completed', () => {
    const plan = parseAgentEvent('plan', {
      revision: 0,
      steps: [{ id: 's1', depends_on: ['a', 2, null, 'b'] }],
    })
    expect(plan).toMatchObject({ steps: [{ dependsOn: ['a', 'b'] }] })

    const budget = parseAgentEvent('budget', { not_completed: ['ok', 3, {}] })
    expect(budget).toMatchObject({ notCompleted: ['ok'] })
  })
})

// ---------------------------------------------------------------------------
// activityLogReducer — pure / immutable fold
// ---------------------------------------------------------------------------

describe('activityLogReducer — scripted turn sequence', () => {
  it('folds initial plan → step started → step finished → replan → rev1 plan → budget', () => {
    const events: AgentEvent[] = [
      parseAgentEvent('plan', {
        revision: 0,
        reason: null,
        steps: [
          {
            id: 's1',
            label: 'Read names',
            source_id: 'u1',
            source_name: 'users.csv',
            depends_on: [],
          },
          { id: 's2', label: 'Query CRM', source_id: 'u2', source_name: 'crm', depends_on: ['s1'] },
        ],
      }),
      parseAgentEvent('step', {
        step_id: 's1',
        role: 'executor',
        state: 'started',
        label: 'Reading users.csv…',
        summary: null,
        progress: { current: 1, total: 2 },
      }),
      parseAgentEvent('step', {
        step_id: 's1',
        role: 'executor',
        state: 'finished',
        label: 'Read users.csv',
        summary: 'Got 7 names',
        progress: { current: 1, total: 2 },
      }),
      parseAgentEvent('replan', {
        reason: 'CRM returned emails; switching to email match',
        superseded_revision: 0,
      }),
      parseAgentEvent('plan', {
        revision: 1,
        reason: 'CRM returned emails; switching to email match',
        steps: [
          {
            id: 's1',
            label: 'Read names',
            source_id: 'u1',
            source_name: 'users.csv',
            depends_on: [],
          },
          {
            id: 's3',
            label: 'Match emails',
            source_id: 'u2',
            source_name: 'crm',
            depends_on: ['s1'],
          },
        ],
      }),
      parseAgentEvent('budget', {
        ceiling_hit: true,
        not_completed: ['Write the full answer'],
        offer_continue: true,
      }),
    ].filter((e): e is AgentEvent => e !== null)

    const finalState = events.reduce(activityLogReducer, emptyActivityState)

    // Active plan is the revision-1 plan.
    expect(finalState.activePlan).not.toBeNull()
    expect(finalState.activePlan?.revision).toBe(1)
    expect(finalState.activePlan?.steps.map((s) => s.id)).toEqual(['s1', 's3'])

    // Superseded plan (revision 0) is RETAINED after the replan.
    expect(finalState.supersededPlan).not.toBeNull()
    expect(finalState.supersededPlan?.revision).toBe(0)
    expect(finalState.supersededPlan?.steps.map((s) => s.id)).toEqual(['s1', 's2'])
    expect(finalState.replanReason).toBe('CRM returned emails; switching to email match')

    // Entry sequence: plan, step(s1 — updated in place), replan, plan, budget.
    // The two s1 step events collapse to ONE entry (update, not append).
    expect(finalState.entries.map((e) => e.kind)).toEqual([
      'plan',
      'step',
      'replan',
      'plan',
      'budget',
    ])

    // The single retained step entry reflects the FINISHED state (last write wins).
    const stepEntries = finalState.entries.filter((e) => e.kind === 'step')
    expect(stepEntries).toHaveLength(1)
    expect(stepEntries[0]).toMatchObject({
      kind: 'step',
      stepId: 's1',
      state: 'finished',
      summary: 'Got 7 names',
    })

    // Budget entry recorded — and it is just an entry, not a terminal signal.
    const budgetEntry = finalState.entries.find((e) => e.kind === 'budget')
    expect(budgetEntry).toMatchObject({
      kind: 'budget',
      ceilingHit: true,
      offerContinue: true,
    })
  })

  it('appends distinct steps but updates the same stepId in place', () => {
    const s1Start = parseAgentEvent('step', {
      step_id: 's1',
      role: 'executor',
      state: 'started',
      progress: { current: 1, total: 2 },
    })
    const s2Start = parseAgentEvent('step', {
      step_id: 's2',
      role: 'verifier',
      state: 'started',
      progress: { current: 2, total: 2 },
    })
    const s1Finished = parseAgentEvent('step', {
      step_id: 's1',
      role: 'executor',
      state: 'finished',
      progress: { current: 1, total: 2 },
    })
    const events = [s1Start, s2Start, s1Finished].filter((e): e is AgentEvent => e !== null)
    const state = events.reduce(activityLogReducer, emptyActivityState)

    // s1 updated in place, s2 appended → two entries, s1 still first.
    expect(state.entries).toHaveLength(2)
    expect(state.entries[0]).toMatchObject({ stepId: 's1', state: 'finished' })
    expect(state.entries[1]).toMatchObject({ stepId: 's2', state: 'started' })
  })
})

describe('activityLogReducer — purity / immutability', () => {
  it('never mutates the input state (returns a new object + new nested arrays)', () => {
    const plan = parseAgentEvent('plan', {
      revision: 0,
      steps: [{ id: 's1', depends_on: ['x'] }],
    })
    if (plan === null) throw new Error('plan should parse')

    const before: ActivityState = emptyActivityState
    const frozenEntries = before.entries

    const after = activityLogReducer(before, plan)

    // New top-level object.
    expect(after).not.toBe(before)
    // Original entries array untouched (still empty, same reference).
    expect(before.entries).toBe(frozenEntries)
    expect(before.entries).toHaveLength(0)
    // New entries array on the output.
    expect(after.entries).not.toBe(before.entries)
    expect(after.entries).toHaveLength(1)

    // Mutating the output must not bleed into a later fold of `before`.
    after.entries.push({
      kind: 'budget',
      ceilingHit: false,
      notCompleted: [],
      offerContinue: false,
    })
    const afterAgain = activityLogReducer(before, plan)
    expect(afterAgain.entries).toHaveLength(1)
  })

  it('does not alias the event payload arrays into the activity state', () => {
    const planEvent = parseAgentEvent('plan', {
      revision: 0,
      steps: [{ id: 's1', depends_on: ['a'] }],
    })
    if (planEvent === null || planEvent.type !== 'plan') throw new Error('plan')

    const state = activityLogReducer(emptyActivityState, planEvent)
    // Mutating the source event's nested array must not affect stored state.
    planEvent.steps[0].dependsOn.push('b')
    expect(state.activePlan?.steps[0].dependsOn).toEqual(['a'])
  })
})

describe('activityLogReducer — no-op safety', () => {
  it('returns a same-shaped state for an unknown event (parseAgentEvent → null skipped by caller)', () => {
    // Unknown wire events never become AgentEvents — the caller skips them.
    // This asserts the contract end-to-end: parse returns null, so there is
    // nothing to fold and the state is unchanged.
    const unknown = parseAgentEvent('delta', { token: 'hi' })
    expect(unknown).toBeNull()

    // And a cast to bypass the union (defensive default branch) leaves state
    // intact. `as unknown as AgentEvent` avoids `any` (Biome's noExplicitAny).
    const bogus = { type: 'mystery' } as unknown as AgentEvent
    const state = activityLogReducer(emptyActivityState, bogus)
    expect(state).toEqual(emptyActivityState)
  })

  it('exposes no terminal flag on ActivityState (intermediate events are additive only)', () => {
    const budget = parseAgentEvent('budget', { ceiling_hit: true, offer_continue: true })
    if (budget === null) throw new Error('budget')
    const state = activityLogReducer(emptyActivityState, budget)

    // The state shape is exactly the four additive fields — no `terminal`,
    // `done`, `sawTerminal`, `messageType`, or `lastMessageId` field exists.
    expect(Object.keys(state).sort()).toEqual([
      'activePlan',
      'entries',
      'replanReason',
      'supersededPlan',
    ])
  })
})
