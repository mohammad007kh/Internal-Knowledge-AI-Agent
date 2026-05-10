/**
 * F9 — "Naming…" shimmer in the sources list.
 *
 * Asserts that the desktop table and the mobile card both branch on
 * `name_status` / `description_status` and render the muted shimmer pill
 * (with em-dash for description) when the AI-naming pipeline is still
 * working. Once the pipeline flips status to `ai_set`, the row renders
 * normally — admins should not have to know AI authored the name.
 */

import type { SourceListItem } from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

// The DatabaseStudyStrip / IngestionStrip / SourceActionCell components are
// well-tested elsewhere and pull in their own data dependencies. Stub them so
// this suite can focus on the name cell.
vi.mock('@/app/(admin)/admin/sources/_components/DatabaseStudyStrip', () => ({
  DatabaseStudyStrip: () => <div data-testid="db-study-strip-stub" />,
}))
vi.mock('@/app/(admin)/admin/sources/_components/IngestionStrip', () => ({
  IngestionStrip: () => <div data-testid="ingestion-strip-stub" />,
}))
vi.mock('@/app/(admin)/admin/sources/_components/SourceActionCell', () => ({
  SourceActionCell: () => <div data-testid="source-action-cell-stub" />,
}))
vi.mock('@/app/(admin)/admin/sources/_components/ActionCell', () => ({
  ActionCell: () => <div data-testid="action-cell-stub" />,
}))

// `SourcesTable` calls `useListSources()` even when the `demoSources` prop is
// supplied (the live hook still drives the polling probe + isLoading guard).
// Short-circuit it so the table skips the loading skeleton and renders the
// demo rows directly.
vi.mock('@/features/sources/hooks/useSources', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/features/sources/hooks/useSources')>()
  return {
    ...actual,
    useListSources: () => ({ data: { items: [], total: 0, limit: 50, offset: 0 }, isLoading: false }),
    useDeleteSource: () => ({ mutate: vi.fn(), isPending: false }),
    useTriggerSync: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, variables: undefined }),
  }
})

import { SourceRowCard } from '../SourceRowCard'
import { SourcesTable } from '../SourcesTable'

function makeSource(overrides: Partial<SourceListItem>): SourceListItem {
  return {
    id: 'src-1',
    name: 'Acme Wiki',
    source_type: 'pdf',
    is_active: false,
    created_at: '2026-01-01T00:00:00Z',
    description: null,
    document_count: 0,
    chunk_count: 0,
    has_upload: false,
    ...overrides,
  }
}

function renderTable(rows: readonly SourceListItem[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<SourcesTable demoSources={rows} />, { wrapper: Wrapper })
}

function renderCard(source: SourceListItem) {
  return render(<SourceRowCard source={source} onDelete={() => {}} />)
}

// All shimmer pills carry the same data-testid; we look up by row context.
function getPills(): HTMLElement[] {
  return screen.queryAllByTestId('pending-name-pill')
}

describe('SourcesTable / SourceRowCard — F9 naming shimmer', () => {
  it('renders the "Naming…" pill instead of the name when name_status === "pending_ai"', () => {
    const source = makeSource({
      id: 'src-pending',
      name: 'placeholder-name-from-server',
      name_status: 'pending_ai',
    })
    renderTable([source])

    const pills = getPills()
    expect(pills.length).toBeGreaterThan(0)
    for (const pill of pills) {
      expect(pill.textContent).toMatch(/Naming…/i)
      expect(pill.className).toMatch(/animate-pulse/)
    }

    // Raw placeholder name must NOT leak into the visible cell.
    expect(screen.queryByText('placeholder-name-from-server')).toBeNull()
  })

  it('renders the actual name normally when name_status === "ai_set"', () => {
    const source = makeSource({
      id: 'src-ai-set',
      name: 'Engineering Handbook',
      name_status: 'ai_set',
    })
    renderTable([source])

    expect(getPills()).toHaveLength(0)
    // Name appears in both the desktop row and the mobile card — at least one is visible.
    expect(screen.getAllByText('Engineering Handbook').length).toBeGreaterThan(0)
  })

  it('renders the actual name normally when name_status is absent (legacy rows)', () => {
    const source = makeSource({
      id: 'src-legacy',
      name: 'Legacy Source',
      // name_status omitted → defaults to user_set behaviour
    })
    renderTable([source])

    expect(getPills()).toHaveLength(0)
    expect(screen.getAllByText('Legacy Source').length).toBeGreaterThan(0)
  })

  it('renders an em-dash when description_status === "pending_ai"', () => {
    const source = makeSource({
      id: 'src-desc-pending',
      name: 'Acme Wiki',
      description: 'placeholder description from server',
      description_status: 'pending_ai',
      // Keep name_status off so we isolate the description branch.
      name_status: 'user_set',
    })
    renderTable([source])

    // Ensure the placeholder description does not leak.
    expect(screen.queryByText('placeholder description from server')).toBeNull()

    // Both the desktop row and the mobile card render an em-dash subtitle.
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThan(0)
  })

  it('mobile SourceRowCard renders the pill when name_status === "pending_ai"', () => {
    const source = makeSource({
      id: 'src-card-pending',
      name: 'placeholder-name',
      name_status: 'pending_ai',
      description: 'placeholder description',
      description_status: 'pending_ai',
      // Pin source_mode so SourceModeBadge renders the "snapshot" pill instead
      // of its missing-mode em-dash fallback — keeps `getByText('—')` below
      // unambiguous and isolated to the description position.
      source_mode: 'snapshot',
    })
    const { container } = renderCard(source)

    const pill = within(container).getByTestId('pending-name-pill')
    expect(pill.textContent).toMatch(/Naming…/i)

    expect(within(container).queryByText('placeholder-name')).toBeNull()
    expect(within(container).getByText('—')).toBeInTheDocument()
  })
})
