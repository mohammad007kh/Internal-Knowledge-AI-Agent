import type { BudgetActivityEntry } from '@/lib/sse/agent-events'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AbstainTurn } from '../AbstainTurn'

function budget(overrides: Partial<BudgetActivityEntry> = {}): BudgetActivityEntry {
  return { kind: 'budget', ceilingHit: false, notCompleted: [], offerContinue: false, ...overrides }
}

describe('AbstainTurn', () => {
  it('renders the calm abstain message (dimmed, with an info icon, no red)', () => {
    const { container } = render(<AbstainTurn message="I couldn't verify that confidently." />)
    expect(screen.getByText(/couldn't verify that confidently/i)).toBeInTheDocument()
    expect(container.querySelector('.bg-muted\\/40')).not.toBeNull()
    expect(container.innerHTML).not.toMatch(/text-red|bg-red/)
  })

  it('does NOT offer continue/stop when the budget did not offer it', () => {
    render(<AbstainTurn message="No grounded answer." budget={budget({ offerContinue: false })} />)
    expect(screen.queryByRole('button', { name: /keep searching/i })).not.toBeInTheDocument()
  })

  it('offers Keep searching / Stop here when offerContinue is true', () => {
    render(<AbstainTurn message="No grounded answer." budget={budget({ offerContinue: true })} />)
    expect(screen.getByRole('button', { name: /keep searching/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop here/i })).toBeInTheDocument()
  })

  it('routes the continue choice to onContinue', async () => {
    const onContinue = vi.fn()
    render(
      <AbstainTurn
        message="No grounded answer."
        budget={budget({ offerContinue: true })}
        onContinue={onContinue}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /keep searching/i }))
    expect(onContinue).toHaveBeenCalledTimes(1)
  })

  it('routes the stop choice to onStop', async () => {
    const onStop = vi.fn()
    render(
      <AbstainTurn
        message="No grounded answer."
        budget={budget({ offerContinue: true })}
        onStop={onStop}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /stop here/i }))
    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it('locks the choice after the first click (no double-fire)', async () => {
    const onContinue = vi.fn()
    render(
      <AbstainTurn
        message="No grounded answer."
        budget={budget({ offerContinue: true })}
        onContinue={onContinue}
      />
    )
    const keep = screen.getByRole('button', { name: /keep searching/i })
    await userEvent.click(keep)
    await userEvent.click(keep) // second click must be a no-op (group disabled)
    expect(onContinue).toHaveBeenCalledTimes(1)
  })

  it('shows the ceiling note in its footer when the ceiling was hit', () => {
    render(<AbstainTurn message="Stopped early." budget={budget({ ceilingHit: true })} />)
    expect(screen.getByText(/reached the research limit/i)).toBeInTheDocument()
  })
})
