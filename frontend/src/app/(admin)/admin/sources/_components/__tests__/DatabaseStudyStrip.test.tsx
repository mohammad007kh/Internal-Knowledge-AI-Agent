import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DatabaseStudyStrip } from '../DatabaseStudyStrip'

/**
 * Smoke tests for the new DB-source ingestion strip.
 *
 * The strip is a pure visual component (no network, no React Query) so we
 * assert pip activation by reading the `data-active` / `data-failed` /
 * `data-studying` attributes the component emits on each pip — that gives us
 * a stable contract without coupling to Tailwind class names.
 */

function activeMap(container: HTMLElement): Record<string, boolean> {
  const pips = container.querySelectorAll<HTMLElement>('[data-pip]')
  const out: Record<string, boolean> = {}
  for (const node of pips) {
    const id = node.getAttribute('data-pip')
    if (id) out[id] = node.getAttribute('data-active') === 'true'
  }
  return out
}

function flagged(
  container: HTMLElement,
  attr: 'data-failed' | 'data-studying'
): string | null {
  const match = container.querySelector<HTMLElement>(`[${attr}="true"]`)
  return match?.getAttribute('data-pip') ?? null
}

describe('DatabaseStudyStrip', () => {
  it('shows all pips inactive when schema_status is null', () => {
    const { container } = render(
      <DatabaseStudyStrip
        schemaStatus={null}
        studyState={null}
        isApproved={false}
        tablesDocumented={null}
        lastErrorPhase={null}
        sourceName="Sales DB"
      />
    )
    const map = activeMap(container)
    expect(map.connected).toBe(false)
    expect(map.inventoried).toBe(false)
    expect(map.documented).toBe(false)
    expect(map.ready).toBe(false)
    expect(map.approved).toBe(false)
  })

  it('marks Connected active once we leave the QUEUED state', () => {
    const { container } = render(
      <DatabaseStudyStrip
        schemaStatus="STUDYING"
        studyState="INVENTORY"
        isApproved={true}
        tablesDocumented={null}
        lastErrorPhase={null}
      />
    )
    const map = activeMap(container)
    expect(map.connected).toBe(true)
    expect(map.inventoried).toBe(true)
    expect(map.documented).toBe(false)
    expect(map.ready).toBe(false)
    expect(map.approved).toBe(true)
  })

  it('marks Documented active during SAMPLING and shows the count', () => {
    const { container, getByText } = render(
      <DatabaseStudyStrip
        schemaStatus="STUDYING"
        studyState="SAMPLING"
        isApproved={true}
        tablesDocumented={42}
        lastErrorPhase={null}
      />
    )
    const map = activeMap(container)
    expect(map.connected).toBe(true)
    expect(map.inventoried).toBe(true)
    expect(map.documented).toBe(true)
    expect(map.ready).toBe(false)
    expect(getByText(/Documented \(42\)/i)).toBeInTheDocument()
  })

  it('marks Ready active for both READY and READY_PARTIAL', () => {
    const { container, rerender } = render(
      <DatabaseStudyStrip
        schemaStatus="READY"
        studyState="READY"
        isApproved={true}
        tablesDocumented={10}
        lastErrorPhase={null}
      />
    )
    expect(activeMap(container).ready).toBe(true)

    rerender(
      <DatabaseStudyStrip
        schemaStatus="READY"
        studyState="READY_PARTIAL"
        isApproved={true}
        tablesDocumented={10}
        lastErrorPhase={null}
      />
    )
    expect(activeMap(container).ready).toBe(true)
  })

  it('shows a spinner anchored on the in-flight pip when STUDYING', () => {
    const { container } = render(
      <DatabaseStudyStrip
        schemaStatus="STUDYING"
        studyState="DESCRIBING"
        isApproved={true}
        tablesDocumented={5}
        lastErrorPhase={null}
      />
    )
    // Documented is the first incomplete pip (Ready is still pending), so
    // the spinner should anchor on `ready`.
    expect(flagged(container, 'data-studying')).toBe('ready')
  })

  it('paints the failed phase red when schema_status is FAILED', () => {
    const { container } = render(
      <DatabaseStudyStrip
        schemaStatus="FAILED"
        studyState="CONNECT_FAILED"
        isApproved={false}
        tablesDocumented={null}
        lastErrorPhase="CONNECT"
      />
    )
    expect(flagged(container, 'data-failed')).toBe('connected')
  })

  it('exposes a role="status" with a screen-reader summary', () => {
    const { getByRole } = render(
      <DatabaseStudyStrip
        schemaStatus="READY"
        studyState="READY"
        isApproved={true}
        tablesDocumented={3}
        lastErrorPhase={null}
        sourceName="Billing"
      />
    )
    const live = getByRole('status')
    expect(live.getAttribute('aria-label')).toContain('Schema study progress for Billing')
    expect(live.getAttribute('aria-label')).toContain('Connected done')
    expect(live.getAttribute('aria-label')).toContain('Approved done')
  })
})
