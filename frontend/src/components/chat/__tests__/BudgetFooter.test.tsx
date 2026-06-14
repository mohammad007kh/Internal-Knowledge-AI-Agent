import type { BudgetActivityEntry } from '@/lib/sse/agent-events'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BudgetFooter } from '../BudgetFooter'

function budget(overrides: Partial<BudgetActivityEntry> = {}): BudgetActivityEntry {
  return { kind: 'budget', ceilingHit: false, notCompleted: [], offerContinue: false, ...overrides }
}

describe('BudgetFooter', () => {
  it('renders nothing within budget and with no cost note', () => {
    const { container } = render(<BudgetFooter budget={budget()} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when budget is null and no cost note', () => {
    const { container } = render(<BudgetFooter budget={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows a quiet cost note when provided (no colour)', () => {
    const { container } = render(<BudgetFooter budget={budget()} costNote="Reviewed 4 sources" />)
    expect(screen.getByText(/reviewed 4 sources/i)).toBeInTheDocument()
    expect(container.innerHTML).not.toMatch(/amber|text-red|bg-red/)
  })

  it('shows an amber-scoped research-limit note when the ceiling was hit', () => {
    const { container } = render(
      <BudgetFooter budget={budget({ ceilingHit: true, notCompleted: ['x', 'y'] })} />
    )
    expect(screen.getByText(/reached the research limit/i)).toBeInTheDocument()
    expect(screen.getByText(/before checking 2 more/i)).toBeInTheDocument()
    // amber is scoped to the qualifier; never a red banner
    expect(container.innerHTML).toMatch(/text-amber-/)
    expect(container.innerHTML).not.toMatch(/text-red|bg-red/)
  })
})
