/**
 * SchemaViewer — admin DB schema viewer (U7).
 *
 * Verifies:
 *   - Loading skeleton during the React Query pending state.
 *   - 404 from the API renders the empty-state copy.
 *   - Renders summary, footer, table count, dialect.
 *   - All tables render; the divider appears between index 29 and 30
 *     (in default Name sort that's after the 30th row), and tables
 *     30+ are visually deemphasized.
 *   - Search filters tables by name (client-side substring match).
 *   - Sort by row count desc reorders.
 *   - Click table row toggles expanded → renders columns + indexes
 *     + relationships.
 *   - PII chip renders next to is_pii_candidate=true columns.
 *   - Sample-values toggle: OFF by default; flipping ON calls
 *     emitSamplesRevealedApi; reveals values; flipping OFF doesn't
 *     call the audit endpoint.
 *   - Partial-coverage banner renders when partial=true.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  type SchemaDocument,
  type SchemaDocumentResponse,
  type SourceDetail,
  type TableDoc,
  SchemaDocumentNotFoundError,
} from '@/lib/api/sources'

// ---------------------------------------------------------------------------
// Mocks — the API client + the trigger-sync hook the Re-study button calls.
// ---------------------------------------------------------------------------

const getSchemaDocumentMock = vi.fn<(id: string) => Promise<SchemaDocumentResponse>>()
const emitSamplesRevealedMock = vi.fn<(id: string) => Promise<void>>()
const triggerSyncMock = vi.fn<(id: string) => Promise<unknown>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    getSchemaDocumentApi: (id: string) => getSchemaDocumentMock(id),
    emitSamplesRevealedApi: (id: string) => emitSamplesRevealedMock(id),
    // Keep triggerSyncApi reachable in case the hook imports it through
    // useTriggerSync. We patch the hook itself below to avoid network calls.
    triggerSyncApi: (id: string) => triggerSyncMock(id),
  }
})

vi.mock('@/features/sources/hooks/useSources', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/features/sources/hooks/useSources')>()
  return {
    ...actual,
    useTriggerSync: () => ({
      mutate: (id: string) => {
        void triggerSyncMock(id)
      },
      isPending: false,
    }),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { SchemaViewer } from '../SchemaViewer'

// ---------------------------------------------------------------------------
// Fixture builders
// ---------------------------------------------------------------------------

function makeTable(overrides: Partial<TableDoc> & { name: string }): TableDoc {
  const base: TableDoc = {
    name: overrides.name,
    kind: 'table',
    row_count_estimate: 100,
    primary_key: ['id'],
    indexes: [],
    columns: [
      {
        name: 'id',
        type: 'uuid',
        native_type: 'uuid',
        nullable: false,
        default: null,
        sample_values: [],
        is_pii_candidate: false,
        inferred: false,
      },
    ],
    relationships: [],
    description: '',
    tags: [],
  }
  return { ...base, ...overrides } satisfies TableDoc
}

function makeDoc(overrides: Partial<SchemaDocument> = {}): SchemaDocument {
  return {
    dialect: 'postgresql',
    fingerprint: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
    generated_at: new Date(Date.now() - 4 * 3600 * 1000).toISOString(),
    agent_version: '0.4.2',
    study_duration_ms: 14_300,
    partial: false,
    phase_errors: [],
    tables: [
      makeTable({ name: 'public.orders', row_count_estimate: 410_000 }),
      makeTable({
        name: 'public.audit_log',
        row_count_estimate: 1_200_000,
        description: 'Append-only audit trail.',
        primary_key: ['id'],
        indexes: [
          { name: 'audit_log_pkey', columns: ['id'], unique: true },
          {
            name: 'idx_audit_log_actor',
            columns: ['actor_id'],
            unique: false,
          },
        ],
        columns: [
          {
            name: 'id',
            type: 'uuid',
            native_type: 'uuid',
            nullable: false,
            default: null,
            sample_values: [],
            is_pii_candidate: false,
            inferred: false,
          },
          {
            name: 'email',
            type: 'text',
            native_type: 'varchar(255)',
            nullable: true,
            default: null,
            sample_values: ['alice@example.com', 'bob@example.com'],
            is_pii_candidate: true,
            inferred: false,
          },
        ],
        relationships: [
          {
            from_columns: ['actor_id'],
            to_table: 'public.users',
            to_columns: ['id'],
            kind: 'foreign_key',
          },
        ],
        tags: ['audit_log'],
      }),
    ],
    summary: 'Two-table demo schema.',
    vector_index_ref: null,
    ...overrides,
  } satisfies SchemaDocument
}

function makeResponse(
  doc: SchemaDocument = makeDoc(),
  overrides: Partial<SchemaDocumentResponse> = {},
): SchemaDocumentResponse {
  return {
    study_id: 'study-1',
    state: 'READY',
    started_at: new Date(Date.now() - 4 * 3600 * 1000).toISOString(),
    finished_at: new Date(Date.now() - 4 * 3600 * 1000 + 14_300).toISOString(),
    fingerprint_short: doc.fingerprint.slice(0, 8),
    schema_document: doc,
    ...overrides,
  } satisfies SchemaDocumentResponse
}

function renderViewer(
  sourceId = 'src-1',
  source: SourceDetail | null = null,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(
    <SchemaViewer sourceId={sourceId} source={source} />,
    { wrapper: Wrapper },
  )
}

/**
 * Minimal SourceDetail factory used by the FX18 four-state tests. The
 * SchemaViewer only reads `schema_status`, `last_error_phase`, and
 * `last_error_message` off the source; everything else is filler the
 * type system demands.
 */
function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  const base: SourceDetail = {
    id: 'src-1',
    name: 'Test DB',
    source_type: 'database',
    is_active: true,
    created_at: new Date().toISOString(),
    source_mode: 'live',
    retrieval_mode: 'text_to_query',
    description: null,
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: false,
    updated_at: new Date().toISOString(),
    owner_email: null,
    schema_summary: null,
  }
  return { ...base, ...overrides } satisfies SourceDetail
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  getSchemaDocumentMock.mockReset()
  emitSamplesRevealedMock.mockReset()
  triggerSyncMock.mockReset()
  emitSamplesRevealedMock.mockResolvedValue(undefined)
  triggerSyncMock.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SchemaViewer — loading and error states', () => {
  it('renders the skeleton while the query is pending', () => {
    // Never resolves — keeps the query in `isPending`.
    getSchemaDocumentMock.mockReturnValue(new Promise(() => {}))
    renderViewer()
    expect(screen.getByTestId('schema-viewer-loading')).toBeInTheDocument()
  })

  it('renders the empty-state copy when the API returns 404', async () => {
    getSchemaDocumentMock.mockRejectedValue(new SchemaDocumentNotFoundError())
    renderViewer()
    const empty = await screen.findByTestId('schema-empty-state')
    expect(empty).toHaveTextContent(/hasn['’]t been studied yet/i)
    expect(empty).toHaveTextContent(/AI catalogs the schema on first sync/i)
    // Inline "Run schema study" action — distinct from the generic
    // pre-FX18 "Re-study schema in the Sync tab" prose.
    expect(
      within(empty).getByTestId('schema-restudy-action'),
    ).toHaveTextContent(/Run schema study/i)
  })
})

// ---------------------------------------------------------------------------
// FX18 — four distinguishable non-ready states
// ---------------------------------------------------------------------------

describe('SchemaViewer — FX18 four-state UX', () => {
  it('STUDYING — shows the in-progress spinner and skips the document fetch', () => {
    const fetchSpy = vi.fn()
    getSchemaDocumentMock.mockImplementation(async (id) => {
      fetchSpy(id)
      // The component should NOT fetch while schema_status is STUDYING.
      return Promise.resolve(makeResponse())
    })
    renderViewer('src-1', makeSource({ schema_status: 'studying' }))

    const studying = screen.getByTestId('schema-studying-state')
    expect(studying).toHaveTextContent(
      /AI is studying the schema right now/i,
    )
    expect(studying).toHaveTextContent(/10[–-]30s/i)
    // ARIA live region for screen readers.
    expect(studying).toHaveAttribute('role', 'status')
    // Critically: do NOT hit the schema-document endpoint while studying —
    // the parent page's `useSource(..., { pollWhileRunning: 'auto' })`
    // already polls and will flip schema_status to READY when done.
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('queued (study_state=QUEUED) — also renders the studying spinner', () => {
    renderViewer('src-1', makeSource({ schema_status: null, study_state: 'QUEUED' }))
    expect(screen.getByTestId('schema-studying-state')).toBeInTheDocument()
  })

  it('FAILED — surfaces the studying agent error phase and message', () => {
    renderViewer(
      'src-1',
      makeSource({
        schema_status: 'failed',
        last_error_phase: 'CONNECT',
        last_error_message: 'Could not reach host on port 5432.',
      }),
    )

    const failed = screen.getByTestId('schema-failed-state')
    expect(failed).toHaveTextContent(/Schema study failed/i)
    expect(within(failed).getByTestId('schema-failed-phase')).toHaveTextContent(
      /CONNECT/,
    )
    expect(
      within(failed).getByTestId('schema-failed-message'),
    ).toHaveTextContent(/Could not reach host on port 5432/i)
    expect(
      within(failed).getByTestId('schema-restudy-action'),
    ).toBeInTheDocument()
  })

  it('FAILED — clicking re-study triggers a new sync', async () => {
    const user = userEvent.setup()
    renderViewer(
      'src-7',
      makeSource({
        id: 'src-7',
        schema_status: 'failed',
        last_error_phase: 'INVENTORY',
        last_error_message: 'Permission denied to schema.',
      }),
    )

    await user.click(screen.getByTestId('schema-restudy-action'))
    await waitFor(() =>
      expect(triggerSyncMock).toHaveBeenCalledWith('src-7'),
    )
  })

  it('READY with zero tables — distinct empty-database state, not generic empty', async () => {
    getSchemaDocumentMock.mockResolvedValue(
      makeResponse(makeDoc({ tables: [] })),
    )
    renderViewer('src-1', makeSource({ schema_status: 'completed' }))

    const emptyDb = await screen.findByTestId(
      'schema-empty-database-state',
    )
    expect(emptyDb).toHaveTextContent(/found no tables/i)
    expect(emptyDb).toHaveTextContent(/postgresql/i)
    expect(emptyDb).toHaveTextContent(/database name/i)
    // The pre-FX18 generic empty-state must NOT also render.
    expect(
      screen.queryByTestId('schema-empty-state'),
    ).not.toBeInTheDocument()
  })

  it('non-404 fetch error — surfaces the backend message via extractApiErrorMessage', async () => {
    const apiError = {
      response: {
        status: 500,
        data: {
          detail: {
            detail: 'Database introspection timed out after 30s.',
            title: 'Internal Server Error',
          },
        },
      },
      message: 'Request failed with status code 500',
    }
    getSchemaDocumentMock.mockRejectedValue(apiError)
    renderViewer('src-1', makeSource({ schema_status: 'completed' }))

    const failed = await screen.findByTestId('schema-failed-state')
    expect(
      within(failed).getByTestId('schema-failed-message'),
    ).toHaveTextContent(/Database introspection timed out after 30s/i)
    // No upstream phase — only the document fetch failed.
    expect(
      within(failed).queryByTestId('schema-failed-phase'),
    ).not.toBeInTheDocument()
  })

  it('null schema_status with 404 — empty state offers "Run schema study"', async () => {
    getSchemaDocumentMock.mockRejectedValue(new SchemaDocumentNotFoundError())
    renderViewer('src-1', makeSource({ schema_status: null }))

    const empty = await screen.findByTestId('schema-empty-state')
    expect(empty).toHaveTextContent(/hasn['’]t been studied yet/i)
    expect(
      within(empty).getByTestId('schema-restudy-action'),
    ).toHaveTextContent(/Run schema study/i)
  })
})

describe('SchemaViewer — header / summary / footer', () => {
  it('renders summary, table count, dialect, and footer line', async () => {
    getSchemaDocumentMock.mockResolvedValue(makeResponse())
    renderViewer()

    await screen.findByTestId('schema-viewer')
    expect(screen.getByTestId('schema-summary')).toHaveTextContent(
      /two-table demo schema/i,
    )
    // Table count + dialect — pulled from the rendered title text.
    const viewer = screen.getByTestId('schema-viewer')
    expect(within(viewer).getByText(/2 tables/i)).toBeInTheDocument()
    expect(within(viewer).getByText(/postgresql/i)).toBeInTheDocument()

    const footer = screen.getByTestId('schema-footer')
    expect(footer).toHaveTextContent(/v0\.4\.2/)
    expect(footer).toHaveTextContent(/a1b2c3d4/)
    expect(footer).toHaveTextContent(/14\.3s/)
    expect(footer).toHaveTextContent(/READY/)
  })
})

describe('SchemaViewer — agent-truncation divider', () => {
  it('renders all 35 tables, with the divider before the first hidden row and 30+ deemphasized', async () => {
    const tables: TableDoc[] = Array.from({ length: 35 }, (_, i) =>
      makeTable({
        // Names sort alphabetically by their numeric suffix (zero-padded).
        name: `public.t${String(i).padStart(2, '0')}`,
        row_count_estimate: 1000 - i,
      }),
    )
    const doc = makeDoc({ tables })
    getSchemaDocumentMock.mockResolvedValue(makeResponse(doc))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    // Every table renders (visible + hidden combined = 35).
    const visibleRows = screen.getAllByTestId('schema-table-row')
    const hiddenRows = screen.getAllByTestId('schema-table-row-hidden')
    expect(visibleRows).toHaveLength(30)
    expect(hiddenRows).toHaveLength(5)

    // Single divider node, sitting before the first hidden row.
    const dividers = screen.getAllByTestId('schema-truncation-divider')
    expect(dividers).toHaveLength(1)
    expect(dividers[0]).toHaveTextContent(/Below this line: not visible to the agent/i)

    // The hidden rows have line-through styling on their name span.
    const firstHiddenName = within(hiddenRows[0]).getByText(/public\.t30/)
    expect(firstHiddenName.className).toMatch(/line-through/)
  })
})

describe('SchemaViewer — search filter', () => {
  it('filters tables client-side by case-insensitive name substring', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer()
    await screen.findByTestId('schema-viewer')

    expect(screen.getAllByTestId('schema-table-row')).toHaveLength(2)

    const input = screen.getByTestId('schema-filter-input')
    await user.type(input, 'audit')

    const remaining = screen.getAllByTestId('schema-table-row')
    expect(remaining).toHaveLength(1)
    expect(remaining[0]).toHaveTextContent(/audit_log/)
    expect(screen.queryByText('public.orders')).not.toBeInTheDocument()
  })
})

describe('SchemaViewer — sort by row count', () => {
  it('reorders the list by row_count_estimate desc when the user picks the option', async () => {
    const user = userEvent.setup()
    // Default doc has orders=410K, audit_log=1.2M. Default sort (Name) puts
    // audit_log first alphabetically; rows-desc must keep audit_log first
    // because it has more rows. To prove sort, reorder the source data so
    // Name and rows-desc would yield different orders.
    const tables: TableDoc[] = [
      makeTable({ name: 'public.alpha', row_count_estimate: 10 }),
      makeTable({ name: 'public.beta', row_count_estimate: 999 }),
      makeTable({ name: 'public.gamma', row_count_estimate: 500 }),
    ]
    getSchemaDocumentMock.mockResolvedValue(makeResponse(makeDoc({ tables })))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    // Default sort = name → alpha, beta, gamma.
    let rows = screen.getAllByTestId('schema-table-row')
    expect(rows.map((r) => r.textContent)).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/alpha/),
        expect.stringMatching(/beta/),
        expect.stringMatching(/gamma/),
      ]),
    )
    // Verify ordering positionally.
    expect(rows[0]).toHaveTextContent(/alpha/)
    expect(rows[1]).toHaveTextContent(/beta/)
    expect(rows[2]).toHaveTextContent(/gamma/)

    // Change sort to row count desc.
    const select = screen.getByTestId('schema-sort-select')
    await user.click(select)
    const option = await screen.findByText(/Row count \(high→low\)/i)
    await user.click(option)

    rows = screen.getAllByTestId('schema-table-row')
    expect(rows[0]).toHaveTextContent(/beta/)
    expect(rows[1]).toHaveTextContent(/gamma/)
    expect(rows[2]).toHaveTextContent(/alpha/)
  })
})

describe('SchemaViewer — table expansion', () => {
  it('clicking a row toggles its expanded section with columns, indexes, and relationships', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer()
    await screen.findByTestId('schema-viewer')

    expect(screen.queryByTestId('schema-table-expanded')).not.toBeInTheDocument()

    // Find audit_log row and click it. The toggle is a button inside the row.
    const auditRow = screen
      .getAllByTestId('schema-table-row')
      .find((r) => r.textContent?.includes('audit_log'))
    if (!auditRow) throw new Error('audit_log row not rendered')

    const button = within(auditRow).getByRole('button')
    await user.click(button)

    const expanded = await screen.findByTestId('schema-table-expanded')
    expect(expanded).toBeInTheDocument()
    expect(expanded).toHaveTextContent(/Append-only audit trail/i)

    // Columns table renders.
    expect(screen.getByTestId('schema-columns-table')).toBeInTheDocument()
    // Indexes list renders.
    expect(screen.getByTestId('schema-indexes-list')).toHaveTextContent(
      /audit_log_pkey/,
    )
    expect(screen.getByTestId('schema-indexes-list')).toHaveTextContent(
      /idx_audit_log_actor/,
    )
    // Relationships list renders with the FK arrow.
    expect(screen.getByTestId('schema-relationships-list')).toHaveTextContent(
      /public\.users/,
    )
  })

  it('renders a PII chip next to columns where is_pii_candidate=true', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const auditRow = screen
      .getAllByTestId('schema-table-row')
      .find((r) => r.textContent?.includes('audit_log'))
    if (!auditRow) throw new Error('audit_log row not rendered')

    await user.click(within(auditRow).getByRole('button'))

    const chips = await screen.findAllByTestId('schema-pii-chip')
    expect(chips).toHaveLength(1)
    // The PII chip is on the email row, not on id.
    const piiChipParent = chips[0].closest('td')
    expect(piiChipParent).toHaveTextContent(/email/)
  })
})

describe('SchemaViewer — sample-values toggle (audit emit)', () => {
  it('is OFF by default and does not call emitSamplesRevealedApi', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer()
    await screen.findByTestId('schema-viewer')

    // Expand audit_log so the columns table is visible.
    const auditRow = screen
      .getAllByTestId('schema-table-row')
      .find((r) => r.textContent?.includes('audit_log'))!
    await user.click(within(auditRow).getByRole('button'))

    // The "Sample values" column header should NOT be present when toggle is OFF.
    // Note: the toggle's own label "Show sample values" is intentionally always
    // present, so we assert on the column header role specifically.
    expect(
      screen.queryByRole('columnheader', { name: /^Sample values$/i }),
    ).not.toBeInTheDocument()
    expect(emitSamplesRevealedMock).not.toHaveBeenCalled()
  })

  it('flipping ON calls emitSamplesRevealedApi and reveals sample-values column', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer('src-7')
    await screen.findByTestId('schema-viewer')

    // Expand the audit_log row to render columns.
    const auditRow = screen
      .getAllByTestId('schema-table-row')
      .find((r) => r.textContent?.includes('audit_log'))!
    await user.click(within(auditRow).getByRole('button'))

    // Flip the switch.
    const toggle = screen.getByTestId('schema-samples-toggle')
    await user.click(toggle)

    await waitFor(() =>
      expect(emitSamplesRevealedMock).toHaveBeenCalledWith('src-7'),
    )
    expect(emitSamplesRevealedMock).toHaveBeenCalledTimes(1)

    // Sample values column now appears, with the email row's values.
    const samples = await screen.findAllByTestId('schema-sample-values')
    expect(samples.length).toBeGreaterThanOrEqual(1)
    const joined = samples.map((s) => s.textContent ?? '').join(' ')
    expect(joined).toContain('alice@example.com')
  })

  it('flipping OFF does NOT call the audit endpoint a second time', async () => {
    const user = userEvent.setup()
    getSchemaDocumentMock.mockResolvedValue(makeResponse())

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const toggle = screen.getByTestId('schema-samples-toggle')
    await user.click(toggle) // ON
    await waitFor(() =>
      expect(emitSamplesRevealedMock).toHaveBeenCalledTimes(1),
    )

    await user.click(toggle) // OFF
    // Still only the one ON call — OFF must be silent.
    expect(emitSamplesRevealedMock).toHaveBeenCalledTimes(1)
  })
})

describe('SchemaViewer — partial coverage banner', () => {
  it('renders the amber banner with each phase_errors entry when partial=true', async () => {
    const doc = makeDoc({
      partial: true,
      phase_errors: [
        {
          phase: 'SAMPLING',
          error_key: 'SAMPLE_TIMEOUT',
          message: 'Sampling timed out for 3 tables.',
        },
        {
          phase: 'DESCRIBING',
          error_key: 'LLM_RATE_LIMIT',
          message: 'AI describer hit rate limit.',
        },
      ],
    })
    getSchemaDocumentMock.mockResolvedValue(makeResponse(doc))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const banner = screen.getByTestId('schema-partial-banner')
    expect(banner).toHaveTextContent(/Partial coverage/i)
    expect(banner).toHaveTextContent(/2 phases failed/i)
    expect(banner).toHaveTextContent(/SAMPLING/)
    expect(banner).toHaveTextContent(/Sampling timed out/i)
    expect(banner).toHaveTextContent(/DESCRIBING/)
    expect(banner).toHaveTextContent(/AI describer hit rate limit/i)
  })

  it('does NOT render the banner when partial=false', async () => {
    getSchemaDocumentMock.mockResolvedValue(makeResponse())
    renderViewer()
    await screen.findByTestId('schema-viewer')
    expect(screen.queryByTestId('schema-partial-banner')).not.toBeInTheDocument()
  })
})

describe('SchemaViewer — FX24 partial-coverage edge cases', () => {
  it('truncated_at — surfaces a banner when the source is bigger than the cap', async () => {
    const doc = makeDoc({
      partial: false,
      truncated_at: 250,
    })
    getSchemaDocumentMock.mockResolvedValue(makeResponse(doc))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const banner = screen.getByTestId('schema-truncation-banner')
    expect(banner).toHaveTextContent(/Large schema/i)
    expect(banner).toHaveTextContent(/showing 2 of 250/i)
  })

  it('skipped_tables — surfaces an amber list of permission-denied tables', async () => {
    const doc = makeDoc({
      partial: true,
      partial_coverage: true,
      skipped_tables: ['public.secrets', 'public.audit_priv'],
      phase_errors: [
        {
          phase: 'SAMPLING',
          error_key: 'SAMPLE_DENIED',
          message: 'Not permitted to read public.secrets',
        },
      ],
    })
    getSchemaDocumentMock.mockResolvedValue(makeResponse(doc))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const banner = screen.getByTestId('schema-skipped-tables-banner')
    expect(banner).toHaveTextContent(/2 tables skipped/i)
    expect(banner).toHaveTextContent(/public\.secrets/)
    expect(banner).toHaveTextContent(/public\.audit_priv/)
  })

  it('llm_descriptions_available=false — surfaces the AI-blurb-missing banner', async () => {
    const doc = makeDoc({
      partial: true,
      llm_descriptions_available: false,
      phase_errors: [
        {
          phase: 'DESCRIBING',
          error_key: 'LLM_ERROR',
          message: 'Upstream timeout.',
        },
      ],
    })
    getSchemaDocumentMock.mockResolvedValue(makeResponse(doc))

    renderViewer()
    await screen.findByTestId('schema-viewer')

    const banner = screen.getByTestId('schema-llm-unavailable-banner')
    expect(banner).toHaveTextContent(/AI descriptions unavailable/i)
  })

  it('does NOT render the new banners when none of the flags are set', async () => {
    getSchemaDocumentMock.mockResolvedValue(makeResponse(makeDoc()))
    renderViewer()
    await screen.findByTestId('schema-viewer')
    expect(screen.queryByTestId('schema-truncation-banner')).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('schema-skipped-tables-banner'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('schema-llm-unavailable-banner'),
    ).not.toBeInTheDocument()
  })
})
