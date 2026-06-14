import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ClarificationCard, type ClarificationOption } from '../ClarificationCard'

const OPTIONS: ClarificationOption[] = [
  { id: 'src-1', label: 'Q4 Financials', hint: 'Spreadsheet', recommended: true },
  { id: 'src-2', label: 'Board Notes' },
]

describe('ClarificationCard', () => {
  it('renders the question calmly (not an alarming warning colour)', () => {
    const { container } = render(
      <ClarificationCard
        question="Which source did you mean?"
        onReply={vi.fn()}
        onDismiss={vi.fn()}
      />
    )
    expect(screen.getByText('Which source did you mean?')).toBeInTheDocument()
    // calm bg-muted/40 styling, no yellow/red alarm
    expect(container.innerHTML).toMatch(/bg-muted\/40/)
    expect(container.innerHTML).not.toMatch(/yellow|bg-red|text-red/)
  })

  it('falls back to a free-text reply when there are no options', async () => {
    const onReply = vi.fn()
    render(<ClarificationCard question="Clarify?" onReply={onReply} onDismiss={vi.fn()} />)
    await userEvent.type(
      screen.getByRole('textbox', { name: /clarification reply/i }),
      'the 2024 one'
    )
    await userEvent.click(screen.getByRole('button', { name: /send clarification reply/i }))
    expect(onReply).toHaveBeenCalledWith('the 2024 one')
  })

  it('renders permitted-source options and replies with the option id (not label)', async () => {
    const onReply = vi.fn()
    render(
      <ClarificationCard
        question="Which source?"
        options={OPTIONS}
        onReply={onReply}
        onDismiss={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /q4 financials/i }))
    expect(onReply).toHaveBeenCalledWith('src-1')
  })

  it('marks the recommended option (sr-only, not colour alone)', () => {
    render(
      <ClarificationCard
        question="Which source?"
        options={OPTIONS}
        onReply={vi.fn()}
        onDismiss={vi.fn()}
      />
    )
    expect(
      screen.getByRole('button', { name: /q4 financials\s*\(recommended\)/i })
    ).toBeInTheDocument()
  })

  it('offers a free-text escape hatch alongside options (allow_free_text)', async () => {
    const onReply = vi.fn()
    render(
      <ClarificationCard
        question="Which source?"
        options={OPTIONS}
        allowFreeText
        onReply={onReply}
        onDismiss={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /something else/i }))
    await userEvent.type(screen.getByPlaceholderText(/something else/i), 'a different doc')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    expect(onReply).toHaveBeenCalledWith('a different doc')
  })

  it('hides the free-text escape hatch when allow_free_text is false', () => {
    render(
      <ClarificationCard
        question="Which source?"
        options={OPTIONS}
        allowFreeText={false}
        onReply={vi.fn()}
        onDismiss={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: /something else/i })).not.toBeInTheDocument()
  })

  it('calls onDismiss from the dismiss button', async () => {
    const onDismiss = vi.fn()
    render(<ClarificationCard question="Clarify?" onReply={vi.fn()} onDismiss={onDismiss} />)
    await userEvent.click(screen.getByRole('button', { name: /dismiss clarification/i }))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('renders no reply affordance when there are no options AND free text is off', () => {
    render(
      <ClarificationCard
        question="Pick one of the offered sources."
        allowFreeText={false}
        onReply={vi.fn()}
        onDismiss={vi.fn()}
      />
    )
    expect(screen.queryByRole('textbox', { name: /clarification reply/i })).not.toBeInTheDocument()
  })

  it('locks after the first option choice (no double-fire)', async () => {
    const onReply = vi.fn()
    render(
      <ClarificationCard
        question="Which source?"
        options={OPTIONS}
        onReply={onReply}
        onDismiss={vi.fn()}
      />
    )
    const btn = screen.getByRole('button', { name: /q4 financials/i })
    await userEvent.click(btn)
    await userEvent.click(btn) // second click must be a no-op
    expect(onReply).toHaveBeenCalledTimes(1)
  })

  it('trims a free-text reply before sending', async () => {
    const onReply = vi.fn()
    render(<ClarificationCard question="Clarify?" onReply={onReply} onDismiss={vi.fn()} />)
    await userEvent.type(
      screen.getByRole('textbox', { name: /clarification reply/i }),
      '  spaced  '
    )
    await userEvent.click(screen.getByRole('button', { name: /send clarification reply/i }))
    expect(onReply).toHaveBeenCalledWith('spaced')
  })
})
