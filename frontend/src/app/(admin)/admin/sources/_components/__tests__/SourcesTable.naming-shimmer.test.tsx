/**
 * F9 + FX14 — list-row name/description rendering.
 *
 * F9: the desktop table and the mobile card both branch on `name_status`
 * and render the muted "Naming…" shimmer pill while the AI naming pipeline
 * is still running. Once status flips to `ai_set`, the row renders normally.
 *
 * FX14: the AI description is NEVER rendered in the list row (regardless of
 * `description_status`), and the title `<Link>` carries `title={source.name}`
 * so the full name remains discoverable when truncated.
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

  it('FX14: never renders the AI description in the list row, regardless of description_status', () => {
    const longDesc =
      'This is a very long AI-generated description that would otherwise consume the whole row and push every other column off-screen, exactly the bug FX14 fixes.'
    const source = makeSource({
      id: 'src-desc-long',
      name: 'Acme Wiki',
      description: longDesc,
      description_status: 'ai_set',
      name_status: 'user_set',
      // Pin source_mode so SourceModeBadge doesn't fall back to its own '—'.
      source_mode: 'snapshot',
    })
    renderTable([source])

    // The full description must not leak into the list row.
    expect(screen.queryByText(longDesc)).toBeNull()
    // And neither does the legacy "—" placeholder we used to show while pending.
    expect(screen.queryAllByText('—')).toHaveLength(0)
  })

  it('FX14: exposes the full name via the `title` attribute when truncated', () => {
    const longName =
      'Extremely Long Source Name That Will Be Truncated In The List Row But Discoverable On Hover'
    const source = makeSource({
      id: 'src-long-name',
      name: longName,
      name_status: 'user_set',
    })
    renderTable([source])

    // The truncated <Link> exposes the full name via title=… for hover discovery.
    const link = screen.getAllByTitle(longName)[0]
    expect(link).toBeDefined()
    expect(link.tagName).toBe('A')
  })

  it('mobile SourceRowCard renders the pill when name_status === "pending_ai" (no description leak)', () => {
    const source = makeSource({
      id: 'src-card-pending',
      name: 'placeholder-name',
      name_status: 'pending_ai',
      description: 'placeholder description',
      description_status: 'pending_ai',
      source_mode: 'snapshot',
    })
    const { container } = renderCard(source)

    const pill = within(container).getByTestId('pending-name-pill')
    expect(pill.textContent).toMatch(/Naming…/i)

    // Neither the placeholder name nor the placeholder description leaks.
    expect(within(container).queryByText('placeholder-name')).toBeNull()
    expect(within(container).queryByText('placeholder description')).toBeNull()
    expect(within(container).queryByText('—')).toBeNull()
  })
})
