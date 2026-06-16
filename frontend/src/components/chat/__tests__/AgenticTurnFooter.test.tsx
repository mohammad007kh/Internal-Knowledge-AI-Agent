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
import { AgenticTurnFooter } from '../AgenticTurnFooter'

function fold(frames: ReadonlyArray<[string, unknown]>): ActivityState {
  return frames
    .map(([t, d]) => parseAgentEvent(t, d))
    .filter((e): e is AgentEvent => e !== null)
    .reduce(activityLogReducer, emptyActivityState)
}

const STEPPED = fold([
  ['plan', { revision: 0, steps: [{ id: 's1', label: 'Read', source_id: 'u', source_name: 'p' }] }],
  ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Read it' }],
])
const CEILING = fold([
  ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Read it' }],
  ['budget', { ceiling_hit: true, not_completed: ['x'], offer_continue: true }],
])

const noop = { onInspectStep: vi.fn(), onSearchAgain: vi.fn(), onLeaveBudget: vi.fn() }

describe('AgenticTurnFooter', () => {
  it('renders nothing for an empty activity log', () => {
    const { container } = render(
      <AgenticTurnFooter
        activity={emptyActivityState}
        isLastAssistant
        isStreaming={false}
        continueDismissed={false}
        {...noop}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders the activity accordion when there are entries', () => {
    render(
      <AgenticTurnFooter
        activity={STEPPED}
        isLastAssistant
        isStreaming={false}
        continueDismissed={false}
        {...noop}
      />
    )
    expect(screen.getByRole('button', { name: /agent activity/i })).toBeInTheDocument()
  })

  it('offers "Search again" on a budget-capped LAST turn and routes the click', async () => {
    const onSearchAgain = vi.fn()
    render(
      <AgenticTurnFooter
        activity={CEILING}
        isLastAssistant
        isStreaming={false}
        continueDismissed={false}
        onInspectStep={vi.fn()}
        onSearchAgain={onSearchAgain}
        onLeaveBudget={vi.fn()}
      />
    )
    expect(screen.getByText(/reached the research limit/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /search again/i }))
    expect(onSearchAgain).toHaveBeenCalledTimes(1)
  })

  it('hides the affordance when NOT the last assistant turn', () => {
    render(
      <AgenticTurnFooter
        activity={CEILING}
        isLastAssistant={false}
        isStreaming={false}
        continueDismissed={false}
        {...noop}
      />
    )
    expect(screen.queryByRole('button', { name: /search again/i })).not.toBeInTheDocument()
  })

  it('hides the affordance while a new turn is streaming', () => {
    render(
      <AgenticTurnFooter
        activity={CEILING}
        isLastAssistant
        isStreaming
        continueDismissed={false}
        {...noop}
      />
    )
    expect(screen.queryByRole('button', { name: /search again/i })).not.toBeInTheDocument()
  })

  it('hides the affordance once dismissed', () => {
    render(
      <AgenticTurnFooter
        activity={CEILING}
        isLastAssistant
        isStreaming={false}
        continueDismissed
        {...noop}
      />
    )
    expect(screen.queryByRole('button', { name: /search again/i })).not.toBeInTheDocument()
  })
})
