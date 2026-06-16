import type { PlanActivityEntry, PlanStep, StepState } from '@/lib/sse/agent-events'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PlanCard, shouldRenderPlanCard } from '../PlanCard'

function planStep(id: string, label = `Step ${id}`): PlanStep {
  return { id, label, sourceId: `src-${id}`, sourceName: `Source ${id}`, dependsOn: [] }
}

function plan(
  steps: PlanStep[],
  revision: 0 | 1 = 0,
  reason: string | null = null
): PlanActivityEntry {
  return { kind: 'plan', revision, reason, steps }
}

describe('shouldRenderPlanCard (FR-008 visibility rule)', () => {
  it('is false for a 1-step, revision-0 plan', () => {
    expect(shouldRenderPlanCard(plan([planStep('s1')]))).toBe(false)
  })
  it('is true for a >=2-step plan', () => {
    expect(shouldRenderPlanCard(plan([planStep('s1'), planStep('s2')]))).toBe(true)
  })
  it('is true for a 1-step plan at revision >= 1', () => {
    expect(shouldRenderPlanCard(plan([planStep('s1')], 1))).toBe(true)
  })
})

describe('PlanCard', () => {
  it('renders nothing when there is no active plan', () => {
    const { container } = render(
      <PlanCard activePlan={null} supersededPlan={null} replanReason={null} stepStates={{}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing for a trivial 1-step revision-0 plan (no clarification)', () => {
    const { container } = render(
      <PlanCard
        activePlan={plan([planStep('s1')])}
        supersededPlan={null}
        replanReason={null}
        stepStates={{}}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders a numbered list for a >=2-step plan', () => {
    render(
      <PlanCard
        activePlan={plan([planStep('s1', 'Read the policy'), planStep('s2', 'Summarize it')])}
        supersededPlan={null}
        replanReason={null}
        stepStates={{}}
      />
    )
    expect(screen.getByText('Read the policy')).toBeInTheDocument()
    expect(screen.getByText('Summarize it')).toBeInTheDocument()
  })

  it('maps each step to its tick state (✓/↻/○/✗), defaulting unknown to pending', () => {
    const stepStates: Record<string, StepState> = { s1: 'finished', s2: 'retrying' }
    render(
      <PlanCard
        activePlan={plan([planStep('s1'), planStep('s2'), planStep('s3')])}
        supersededPlan={null}
        replanReason={null}
        stepStates={stepStates}
      />
    )
    expect(screen.getByText('done')).toBeInTheDocument() // s1 finished
    expect(screen.getByText('retrying')).toBeInTheDocument() // s2 retrying
    expect(screen.getByText('pending')).toBeInTheDocument() // s3 unknown -> pending
  })

  it('shows a one-line replan note (amber, no strikethrough)', () => {
    const { container } = render(
      <PlanCard
        activePlan={plan([planStep('s1'), planStep('s2')], 1)}
        supersededPlan={plan([planStep('s1'), planStep('sX', 'Old step')])}
        replanReason="CRM returned emails; switching to email match"
        stepStates={{}}
      />
    )
    expect(screen.getByText(/plan updated/i)).toBeInTheDocument()
    expect(container.innerHTML).toMatch(/text-amber-/)
    expect(container.innerHTML).not.toMatch(/line-through/)
  })

  it('collapses the superseded plan behind a disclosure (no strikethrough)', () => {
    render(
      <PlanCard
        activePlan={plan([planStep('s1'), planStep('s2')], 1)}
        supersededPlan={plan([planStep('s1'), planStep('sX', 'Old step')])}
        replanReason="switched approach"
        stepStates={{}}
      />
    )
    expect(screen.getByText(/original plan \(superseded\)/i)).toBeInTheDocument()
  })

  it('does not render a superseded disclosure when there is none', () => {
    render(
      <PlanCard
        activePlan={plan([planStep('s1'), planStep('s2')])}
        supersededPlan={null}
        replanReason={null}
        stepStates={{}}
      />
    )
    expect(screen.queryByText(/superseded/i)).not.toBeInTheDocument()
  })
})
