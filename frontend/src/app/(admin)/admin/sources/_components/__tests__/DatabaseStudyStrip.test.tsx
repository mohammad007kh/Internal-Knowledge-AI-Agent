import type { SourceListItem, SyncJob } from '@/lib/api/sources'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DatabaseStudyStrip } from '../DatabaseStudyStrip'

/**
 * FX34 — the list-row DB strip now mirrors the source-detail-page lifecycle
 * vocabulary (`Queued → Naming with AI → Studying schema → Ready`) driven by
 * `derivePhase` from `@/features/sources/lifecycle`. These tests assert the
 * new contract.
 *
 * The strip is a pure visual component (no network, no React Query) so we
 * assert pip activation by reading the `data-pip` / `data-active` /
 * `data-failed` / `data-studying` attributes the component emits on each pip —
 * that gives us a stable contract without coupling to Tailwind class names.
 *
 * Pip phase ids (matching the lifecycle `Phase` enum):
 *   `pending_upload` — labelled "Queued"
 *   `naming`         — labelled "Naming with AI"
 *   `analyzing`      — labelled "Studying schema"
 *   `ready`          — labelled "Ready"
 */

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'success',
    started_at: '2026-05-09T00:00:00Z',
    finished_at: '2026-05-09T00:05:00Z',
    completed_at: '2026-05-09T00:05:00Z',
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:05:00Z',
    ...overrides,
  }
}

function makeDbSource(overrides: Partial<SourceListItem> = {}): SourceListItem {
  return {
    id: 'src-db-1',
    name: 'Sales DB',
    source_type: 'database',
    is_active: false,
    created_at: '2026-05-09T00:00:00Z',
    source_mode: 'live',
    sync_mode: 'manual',
    last_synced_at: null,
    description: null,
    latest_job: null,
    document_count: 0,
    chunk_count: 0,
    has_upload: false,
    schema_status: null,
    study_state: null,
    tables_documented: null,
    tables_partial: null,
    last_error_phase: null,
    last_error_message: null,
    ...overrides,
  }
}

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

describe('DatabaseStudyStrip — FX34 unified lifecycle vocabulary', () => {
  it('exposes exactly the four DB lifecycle pips (no Approved pip)', () => {
    const { container } = render(
      <DatabaseStudyStrip source={makeDbSource({ schema_status: 'studying' })} />
    )
    const pipIds = Array.from(
      container.querySelectorAll<HTMLElement>('[data-pip]')
    ).map((node) => node.getAttribute('data-pip'))
    expect(pipIds).toEqual(['pending_upload', 'naming', 'analyzing', 'ready'])
    // FX34: the "Approved" pip is intentionally absent — approval is not a
    // worker phase; the Mode badge + "Next step" verb cell carry that signal.
    expect(pipIds).not.toContain('approved')
  })

  it('renders the new label vocabulary', () => {
    const { getByText } = render(
      <DatabaseStudyStrip source={makeDbSource({ schema_status: 'studying' })} />
    )
    expect(getByText('Queued')).toBeInTheDocument()
    expect(getByText('Naming with AI')).toBeInTheDocument()
    expect(getByText('Studying schema')).toBeInTheDocument()
    expect(getByText('Ready')).toBeInTheDocument()
    // Old vocabulary must NOT appear.
    expect(() => getByText('Connected')).toThrow()
    expect(() => getByText('Inventoried')).toThrow()
    expect(() => getByText('Documented')).toThrow()
    expect(() => getByText('Approved')).toThrow()
  })

  it('marks all pips up to and including `analyzing` active while STUDYING', () => {
    const { container } = render(
      <DatabaseStudyStrip source={makeDbSource({ schema_status: 'studying' })} />
    )
    const map = activeMap(container)
    expect(map.pending_upload).toBe(true)
    expect(map.naming).toBe(true)
    expect(map.analyzing).toBe(true)
    expect(map.ready).toBe(false)
  })

  it('anchors the spinner on the `analyzing` pip while STUDYING', () => {
    const { container } = render(
      <DatabaseStudyStrip source={makeDbSource({ schema_status: 'studying' })} />
    )
    expect(flagged(container, 'data-studying')).toBe('analyzing')
  })

  it('marks every pip active when the schema study is completed (ready)', () => {
    const source = makeDbSource({
      // The wire actually carries the lowercase 'completed' token written
      // by SourceRepository.set_schema_status — same cast `lifecycle.ts`
      // uses on its `ready` shortcut.
      schema_status: 'completed' as unknown as SourceListItem['schema_status'],
      is_active: true,
    })
    const { container } = render(<DatabaseStudyStrip source={source} />)
    const map = activeMap(container)
    expect(map.pending_upload).toBe(true)
    expect(map.naming).toBe(true)
    expect(map.analyzing).toBe(true)
    expect(map.ready).toBe(true)
    // No spinner / no failure overlay on a ready source.
    expect(flagged(container, 'data-studying')).toBeNull()
    expect(flagged(container, 'data-failed')).toBeNull()
  })

  it('paints the failure red on `analyzing` when last_error_phase is INVENTORY', () => {
    const source = makeDbSource({
      schema_status: 'failed',
      last_error_phase: 'INVENTORY',
      last_error_message: 'Could not list tables',
    })
    const { container } = render(<DatabaseStudyStrip source={source} />)
    expect(flagged(container, 'data-failed')).toBe('analyzing')
  })

  it('paints the failure red on `pending_upload` for a CONNECT failure', () => {
    const source = makeDbSource({
      schema_status: 'failed',
      last_error_phase: 'CONNECT',
      last_error_message: 'TCP timeout',
    })
    const { container } = render(<DatabaseStudyStrip source={source} />)
    expect(flagged(container, 'data-failed')).toBe('pending_upload')
  })

  it('falls back to `analyzing` for a FAILED source with no last_error_phase', () => {
    const source = makeDbSource({ schema_status: 'failed' })
    const { container } = render(<DatabaseStudyStrip source={source} />)
    expect(flagged(container, 'data-failed')).toBe('analyzing')
  })

  it('treats a `naming` phase (pending_ai name) as in-flight on the naming pip', () => {
    // No schema_status set → lifecycle sees a queued/pending-name source. We
    // pin `name_status='pending_ai'` so `derivePhase` lands on `naming`.
    const source = makeDbSource({
      schema_status: null,
      name_status: 'pending_ai',
    })
    const { container } = render(<DatabaseStudyStrip source={source} />)
    const map = activeMap(container)
    expect(map.pending_upload).toBe(true)
    expect(map.naming).toBe(true)
    expect(map.analyzing).toBe(false)
    expect(map.ready).toBe(false)
    expect(flagged(container, 'data-studying')).toBe('naming')
  })

  it('exposes role="status" with the screen-reader summary in new vocabulary', () => {
    const { getByRole } = render(
      <DatabaseStudyStrip
        source={makeDbSource({
          name: 'Billing',
          schema_status: 'completed' as unknown as SourceListItem['schema_status'],
          is_active: true,
          latest_job: makeJob({ status: 'success' }),
        })}
      />
    )
    const live = getByRole('status')
    const label = live.getAttribute('aria-label') ?? ''
    expect(label).toContain('Schema study progress for Billing')
    expect(label).toContain('Queued done')
    expect(label).toContain('Studying schema done')
    expect(label).toContain('Ready done')
    // Old vocabulary should be gone from the summary too.
    expect(label).not.toContain('Connected')
    expect(label).not.toContain('Approved')
  })
})
