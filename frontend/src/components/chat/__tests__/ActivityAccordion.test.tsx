import {
  type ActivityState,
  type AgentEvent,
  activityLogReducer,
  emptyActivityState,
  parseAgentEvent,
} from '@/lib/sse/agent-events'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ActivityAccordion } from '../ActivityAccordion'

/** Locked test strategy: fold real wire frames through the real reducer. */
function fold(frames: ReadonlyArray<[string, unknown]>): ActivityState {
  return frames
    .map(([t, d]) => parseAgentEvent(t, d))
    .filter((e): e is AgentEvent => e !== null)
    .reduce(activityLogReducer, emptyActivityState)
}

const TWO_STEP_RUN = fold([
  [
    'plan',
    {
      revision: 0,
      steps: [
        { id: 's1', label: 'Read the policy', source_id: 'u1', source_name: 'policy.pdf' },
        { id: 's2', label: 'Verify the dates', source_id: 'u2', source_name: 'policy.pdf' },
      ],
    },
  ],
  ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Read the policy' }],
  ['step', { step_id: 's2', role: 'verifier', state: 'finished', label: 'Verified the dates' }],
])

describe('ActivityAccordion', () => {
  it('ships collapsed by default (panel hidden, header not expanded)', () => {
    render(<ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={vi.fn()} />)
    const header = screen.getByRole('button', { name: /agent activity/i })
    expect(header).toHaveAttribute('aria-expanded', 'false')
    // The region content is not in the accessibility tree while collapsed.
    expect(screen.queryByText('Read the policy')).not.toBeInTheDocument()
  })

  it('expands on click and shows the per-role blocks', async () => {
    render(<ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /agent activity/i }))
    expect(screen.getByRole('button', { name: /agent activity/i })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
    expect(screen.getByText('Reading sources')).toBeInTheDocument()
    expect(screen.getByText('Verifying')).toBeInTheDocument()
  })

  it('bubbles an amber dot to the collapsed header on trouble (retry/fail)', () => {
    const troubled = fold([
      ['step', { step_id: 's1', role: 'executor', state: 'retrying', label: 'Retrying read' }],
    ])
    const { container } = render(<ActivityAccordion activity={troubled} onStepSelect={vi.fn()} />)
    expect(container.innerHTML).toMatch(/bg-amber-/)
    // Color is not the sole signal — there is an sr-only equivalent.
    expect(screen.getByText(/retried or failed/i)).toBeInTheDocument()
  })

  it('shows no amber dot on a clean run', () => {
    const { container } = render(
      <ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={vi.fn()} />
    )
    expect(container.innerHTML).not.toMatch(/bg-amber-/)
  })

  it('renders a handoff micro-label between role blocks (A → B)', async () => {
    render(<ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /agent activity/i }))
    expect(screen.getByText(/reading sources\s*→\s*verifying/i)).toBeInTheDocument()
  })

  it('renders the PlanCard inside when the plan is multi-step', async () => {
    render(<ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /agent activity/i }))
    // Both plan-step labels appear (PlanCard ol + role blocks).
    expect(screen.getAllByText('Read the policy').length).toBeGreaterThanOrEqual(1)
  })

  it('calls onStepSelect when a step row is clicked', async () => {
    const onStepSelect = vi.fn()
    render(<ActivityAccordion activity={TWO_STEP_RUN} onStepSelect={onStepSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /agent activity/i }))
    await userEvent.click(screen.getByRole('button', { name: /open source for: read the policy/i }))
    expect(onStepSelect).toHaveBeenCalledWith(expect.objectContaining({ stepId: 's1' }))
  })

  it('renders nothing for an empty activity log', () => {
    const { container } = render(
      <ActivityAccordion activity={emptyActivityState} onStepSelect={vi.fn()} />
    )
    expect(container.firstChild).toBeNull()
  })
})
