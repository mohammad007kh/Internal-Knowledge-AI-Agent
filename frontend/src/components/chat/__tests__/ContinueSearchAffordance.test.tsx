import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ContinueSearchAffordance, KEEP_SEARCHING_PROMPT } from '../ContinueSearchAffordance'

describe('ContinueSearchAffordance', () => {
  it('uses honest copy — "Search again"/"Leave it here", not "Keep searching"/"Continue"', () => {
    render(<ContinueSearchAffordance onSearchAgain={vi.fn()} onLeave={vi.fn()} />)
    expect(screen.getByRole('button', { name: /search again/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /leave it here/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /keep searching|continue|resume/i })).toBeNull()
  })

  it('shows the calm budget lead-in (no alarm)', () => {
    render(<ContinueSearchAffordance onSearchAgain={vi.fn()} onLeave={vi.fn()} />)
    expect(screen.getByText(/stay within budget.*another pass/i)).toBeInTheDocument()
  })

  it('routes "Search again" to onSearchAgain', async () => {
    const onSearchAgain = vi.fn()
    render(<ContinueSearchAffordance onSearchAgain={onSearchAgain} onLeave={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /search again/i }))
    expect(onSearchAgain).toHaveBeenCalledTimes(1)
  })

  it('routes "Leave it here" to onLeave', async () => {
    const onLeave = vi.fn()
    render(<ContinueSearchAffordance onSearchAgain={vi.fn()} onLeave={onLeave} />)
    await userEvent.click(screen.getByRole('button', { name: /leave it here/i }))
    expect(onLeave).toHaveBeenCalledTimes(1)
  })

  it('locks after the first choice (no double-fire)', async () => {
    const onSearchAgain = vi.fn()
    render(<ContinueSearchAffordance onSearchAgain={onSearchAgain} onLeave={vi.fn()} />)
    const btn = screen.getByRole('button', { name: /search again/i })
    await userEvent.click(btn)
    await userEvent.click(btn)
    expect(onSearchAgain).toHaveBeenCalledTimes(1)
  })

  it('exports a static, deterministic follow-up prompt (no interpolation)', () => {
    expect(KEEP_SEARCHING_PROMPT).toMatch(/another pass/i)
    expect(KEEP_SEARCHING_PROMPT).not.toMatch(/\$\{|undefined|\[object/)
  })
})
