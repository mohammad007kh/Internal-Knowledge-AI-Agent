import type { AgentRole, BudgetActivityEntry, StepActivityEntry } from '@/lib/sse/agent-events'
import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatusLine } from '../StatusLine'

function step(overrides: Partial<StepActivityEntry> = {}): StepActivityEntry {
  return {
    kind: 'step',
    stepId: 's1',
    role: 'executor',
    state: 'started',
    label: 'Reading the onboarding policy',
    summary: null,
    progress: { current: 0, total: 0 },
    ...overrides,
  }
}

function budget(overrides: Partial<BudgetActivityEntry> = {}): BudgetActivityEntry {
  return { kind: 'budget', ceilingHit: false, notCompleted: [], offerContinue: false, ...overrides }
}

describe('StatusLine', () => {
  it('shows a calm thinking indicator before any step has narrated', () => {
    render(<StatusLine activeStep={null} isStreaming={false} />)
    expect(screen.getByText(/thinking/i)).toBeInTheDocument()
  })

  it('renders the current step label', () => {
    render(<StatusLine activeStep={step()} isStreaming={false} />)
    expect(screen.getByText('Reading the onboarding policy')).toBeInTheDocument()
  })

  it('hides progress N/M until a plan exists (progress.total === 0)', () => {
    render(
      <StatusLine activeStep={step({ progress: { current: 0, total: 0 } })} isStreaming={false} />
    )
    expect(screen.queryByText(/\d+\/\d+/)).not.toBeInTheDocument()
  })

  it('shows progress N/M once a plan exists (progress.total > 0)', () => {
    render(
      <StatusLine activeStep={step({ progress: { current: 2, total: 4 } })} isStreaming={false} />
    )
    expect(screen.getByText(/2\/4/)).toBeInTheDocument()
  })

  it('is amber (never red) on a retrying step', () => {
    const { container } = render(
      <StatusLine activeStep={step({ state: 'retrying' })} isStreaming={false} />
    )
    const html = container.innerHTML
    expect(html).toMatch(/amber/)
    expect(html).not.toMatch(/text-red|bg-red/)
  })

  it('shows the success ✓ (emerald) when the current step finished', () => {
    const { container } = render(
      <StatusLine activeStep={step({ state: 'finished' })} isStreaming={false} />
    )
    expect(container.innerHTML).toMatch(/emerald/)
  })

  it('shows a calm wrap-up label (not amber) when the budget ceiling was hit', () => {
    const { container } = render(
      <StatusLine
        activeStep={step({ state: 'started' })}
        budget={budget({ ceilingHit: true })}
        isStreaming={false}
      />
    )
    expect(screen.getByText(/wrapping up/i)).toBeInTheDocument()
    // Wrap-up is calm: not an error colour.
    expect(container.innerHTML).not.toMatch(/text-red|bg-red/)
    // And it supersedes step progress.
    expect(screen.queryByText(/\d+\/\d+/)).not.toBeInTheDocument()
  })

  it('yields (renders no status content) once the answer is streaming', () => {
    render(<StatusLine activeStep={step({ progress: { current: 2, total: 4 } })} isStreaming />)
    expect(screen.queryByText('Reading the onboarding policy')).not.toBeInTheDocument()
    expect(screen.queryByText(/2\/4/)).not.toBeInTheDocument()
  })

  it('exposes a polite, atomic live region for the thinking phase', () => {
    const { container } = render(<StatusLine activeStep={step()} isStreaming={false} />)
    const live = container.querySelector('[aria-live="polite"]')
    expect(live).not.toBeNull()
    expect(live?.getAttribute('aria-atomic')).toBe('true')
  })

  it('truncates the label (single line, no wrap)', () => {
    render(<StatusLine activeStep={step()} isStreaming={false} />)
    expect(screen.getByText('Reading the onboarding policy').className).toMatch(/truncate/)
  })

  it('is amber (never red) on a failed step too', () => {
    const { container } = render(
      <StatusLine activeStep={step({ state: 'failed' })} isStreaming={false} />
    )
    expect(container.innerHTML).toMatch(/text-amber-/)
    expect(container.innerHTML).not.toMatch(/(text|bg)-red-/)
  })

  it('adds an sr-only trouble token so trouble is not signalled by colour alone', () => {
    render(<StatusLine activeStep={step({ state: 'retrying' })} isStreaming={false} />)
    expect(screen.getByText(/retrying:/i)).toBeInTheDocument()
    render(<StatusLine activeStep={step({ state: 'failed', stepId: 's2' })} isStreaming={false} />)
    expect(screen.getByText(/failed:/i)).toBeInTheDocument()
  })

  it('maps each role to a DISTINCT lucide glyph (role identity is the icon, never colour)', () => {
    const glyphOf = (role: AgentRole) => {
      const { container, unmount } = render(
        <StatusLine activeStep={step({ role, state: 'started' })} isStreaming={false} />
      )
      const cls = container.querySelector('svg')?.getAttribute('class') ?? ''
      unmount()
      return cls.match(/lucide-[\w-]+/)?.[0] ?? cls
    }
    const roles: AgentRole[] = ['planner', 'executor', 'verifier', 'synthesizer']
    const glyphs = roles.map(glyphOf)
    expect(new Set(glyphs).size).toBe(roles.length)
  })

  it('stays ONE mutating line across rerenders (never a stacking log)', () => {
    const { container, rerender } = render(
      <StatusLine activeStep={step({ stepId: 's1', label: 'Reading A' })} isStreaming={false} />
    )
    rerender(
      <StatusLine activeStep={step({ stepId: 's2', label: 'Reading B' })} isStreaming={false} />
    )
    // The live region holds exactly one status paragraph, not an append log.
    const live = container.querySelector('[aria-live="polite"]')
    expect(live?.querySelectorAll('p')).toHaveLength(1)
    expect(screen.getByText('Reading B')).toBeInTheDocument()
    expect(screen.queryByText('Reading A')).not.toBeInTheDocument()
  })

  describe('✓-flash timer', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('flashes the ✓ (~600ms) once when a step finishes, then settles', () => {
      vi.useFakeTimers()
      const { container } = render(
        <StatusLine activeStep={step({ stepId: 's1', state: 'finished' })} isStreaming={false} />
      )
      // Immediately after finishing, the success glyph carries the motion-safe pulse.
      expect(container.innerHTML).toMatch(/motion-safe:animate-pulse/)
      act(() => {
        vi.advanceTimersByTime(601)
      })
      // After the flash window the ✓ remains (emerald) but no longer pulses.
      expect(container.innerHTML).toMatch(/text-emerald-/)
      expect(container.innerHTML).not.toMatch(/motion-safe:animate-pulse/)
    })

    it('does not re-flash the SAME finished step on an unrelated rerender', () => {
      vi.useFakeTimers()
      const finished = step({ stepId: 's1', state: 'finished' })
      const { container, rerender } = render(
        <StatusLine activeStep={finished} isStreaming={false} />
      )
      act(() => {
        vi.advanceTimersByTime(601)
      })
      expect(container.innerHTML).not.toMatch(/motion-safe:animate-pulse/)
      // Rerender with the same finished step → guard prevents a fresh flash.
      rerender(<StatusLine activeStep={{ ...finished }} isStreaming={false} />)
      expect(container.innerHTML).not.toMatch(/motion-safe:animate-pulse/)
    })
  })
})
