import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { OptionButtonGroup, type QuickReplyOption } from '../OptionButtonGroup'

const OPTS: QuickReplyOption[] = [
  { id: 'a', label: 'Keep searching', value: 'continue', recommended: true },
  { id: 'b', label: 'Stop here', value: 'stop' },
]

describe('OptionButtonGroup', () => {
  it('renders a labelled group of real buttons', () => {
    render(<OptionButtonGroup label="Keep going?" options={OPTS} onSelect={vi.fn()} />)
    expect(screen.getByRole('group', { name: /keep going/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /keep searching/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop here/i })).toBeInTheDocument()
  })

  it('calls onSelect with the option value (not the label) when clicked', async () => {
    const onSelect = vi.fn()
    render(<OptionButtonGroup options={OPTS} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /stop here/i }))
    expect(onSelect).toHaveBeenCalledWith('stop', expect.objectContaining({ id: 'b' }))
  })

  it('announces the recommended option with an sr-only token (not colour alone)', () => {
    render(<OptionButtonGroup options={OPTS} onSelect={vi.fn()} />)
    expect(
      screen.getByRole('button', { name: /keep searching\s*\(recommended\)/i })
    ).toBeInTheDocument()
  })

  it('disables all options when disabled', () => {
    render(<OptionButtonGroup options={OPTS} onSelect={vi.fn()} disabled />)
    for (const opt of OPTS) {
      expect(screen.getByRole('button', { name: new RegExp(opt.label, 'i') })).toBeDisabled()
    }
  })

  it('offers a free-text escape hatch that submits via onFreeText', async () => {
    const onFreeText = vi.fn()
    render(
      <OptionButtonGroup
        options={OPTS}
        onSelect={vi.fn()}
        allowFreeText
        freeTextPlaceholder="Describe it…"
        onFreeText={onFreeText}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /describe it/i }))
    await userEvent.type(screen.getByPlaceholderText(/describe it/i), 'the 2024 policy')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    expect(onFreeText).toHaveBeenCalledWith('the 2024 policy')
  })

  it('does not render a free-text affordance unless allowFreeText', () => {
    render(<OptionButtonGroup options={OPTS} onSelect={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /something else/i })).not.toBeInTheDocument()
  })

  it('resets the open free-text escape hatch when resetKey changes (no leak across rounds)', async () => {
    const { rerender } = render(
      <OptionButtonGroup
        options={OPTS}
        onSelect={vi.fn()}
        allowFreeText
        onFreeText={vi.fn()}
        resetKey="round-1"
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /something else/i }))
    await userEvent.type(screen.getByPlaceholderText(/something else/i), 'half-typed')
    expect(screen.getByPlaceholderText(/something else/i)).toHaveValue('half-typed')

    // New clarification round → input collapses back to the toggle, value gone.
    rerender(
      <OptionButtonGroup
        options={OPTS}
        onSelect={vi.fn()}
        allowFreeText
        onFreeText={vi.fn()}
        resetKey="round-2"
      />
    )
    expect(screen.queryByPlaceholderText(/something else/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /something else/i })).toBeInTheDocument()
  })

  it('exposes aria-expanded on the free-text toggle', () => {
    render(<OptionButtonGroup options={OPTS} onSelect={vi.fn()} allowFreeText />)
    expect(screen.getByRole('button', { name: /something else/i })).toHaveAttribute(
      'aria-expanded',
      'false'
    )
  })
})
