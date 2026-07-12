import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StepStatusBadge } from '../StepStatusBadge'

describe('StepStatusBadge', () => {
  it('renders an sr-only label for every state (color is never the sole signal)', () => {
    const cases: Array<[Parameters<typeof StepStatusBadge>[0]['state'], RegExp]> = [
      ['pending', /pending/i],
      ['started', /in progress/i],
      ['finished', /done/i],
      ['retrying', /retrying/i],
      ['failed', /failed/i],
    ]
    for (const [state, label] of cases) {
      const { unmount } = render(<StepStatusBadge state={state} />)
      expect(screen.getByText(label)).toBeInTheDocument()
      unmount()
    }
  })

  it('uses amber (never red) for retrying', () => {
    const { container } = render(<StepStatusBadge state="retrying" />)
    const html = container.innerHTML
    expect(html).toMatch(/text-amber-/)
    expect(html).not.toMatch(/(text|bg|border)-red-/)
  })

  it('uses amber (never red) for failed', () => {
    const { container } = render(<StepStatusBadge state="failed" />)
    const html = container.innerHTML
    expect(html).toMatch(/text-amber-/)
    expect(html).not.toMatch(/(text|bg|border)-red-/)
  })

  it('uses emerald for finished (the success tick)', () => {
    const { container } = render(<StepStatusBadge state="finished" />)
    expect(container.innerHTML).toMatch(/text-emerald-/)
  })

  it('keeps pending/started neutral (muted, no amber/emerald/red)', () => {
    for (const state of ['pending', 'started'] as const) {
      const { container, unmount } = render(<StepStatusBadge state={state} />)
      const html = container.innerHTML
      expect(html).toMatch(/muted-foreground/)
      expect(html).not.toMatch(/text-amber-|text-emerald-|(text|bg|border)-red-/)
      unmount()
    }
  })

  it('renders a DISTINCT glyph per state (an icon swap would not slip through)', () => {
    const classOf = (state: Parameters<typeof StepStatusBadge>[0]['state']) => {
      const { container, unmount } = render(<StepStatusBadge state={state} />)
      const cls = container.querySelector('svg')?.getAttribute('class') ?? ''
      unmount()
      // lucide encodes the icon name as a `lucide-<name>` class.
      const match = cls.match(/lucide-[\w-]+/)?.[0] ?? cls
      return match
    }
    const glyphs = (['pending', 'started', 'finished', 'retrying', 'failed'] as const).map(classOf)
    expect(new Set(glyphs).size).toBe(glyphs.length) // all distinct
  })

  it('marks the glyph aria-hidden (meaning carried by the sr-only label)', () => {
    const { container } = render(<StepStatusBadge state="finished" />)
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('merges a caller-supplied className onto the glyph', () => {
    const { container } = render(<StepStatusBadge state="pending" className="h-5 w-5" />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('class')).toMatch(/h-5/)
  })
})
