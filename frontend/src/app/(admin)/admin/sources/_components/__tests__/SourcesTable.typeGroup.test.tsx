/**
 * FX8 — the "Database" category filter on /admin/sources matched zero rows.
 *
 * Root cause was a fictional per-dialect type set (`['postgresql', 'mysql',
 * 'mssql', 'mongodb']`) used for grouping, while the backend StrEnum actually
 * emits the literal `'database'`. `getTypeGroup('database')` fell through to
 * the wrong group → the toolbar's "Database" chip selected nothing.
 *
 * These tests pin:
 *   1. `getTypeGroup` maps the real backend enum values to the right groups.
 *   2. Rendering the table, flipping the type filter to "Database", shows a
 *      `source_type === 'database'` row and hides a `file_upload` row.
 */

import type { SourceListItem } from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

// These children pull in their own data dependencies / heavy UI; stub them so
// this suite stays focused on the type-group filter logic.
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

// `SourcesTable` always calls `useListSources()` (it drives the polling probe
// + isLoading guard) even when `demoSources` is supplied. Short-circuit it so
// the table skips the loading skeleton and renders the demo rows directly.
vi.mock('@/features/sources/hooks/useSources', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/features/sources/hooks/useSources')>()
  return {
    ...actual,
    useListSources: () => ({
      data: { items: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
    }),
    useDeleteSource: () => ({ mutate: vi.fn(), isPending: false }),
    useTriggerSync: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      variables: undefined,
    }),
  }
})

import { SourcesTable, getTypeGroup } from '../SourcesTable'

function makeSource(overrides: Partial<SourceListItem>): SourceListItem {
  return {
    id: 'src-1',
    name: 'Some Source',
    source_type: 'file_upload',
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

describe('getTypeGroup — FX8', () => {
  it('maps the literal backend "database" enum value to the "database" group', () => {
    expect(getTypeGroup('database')).toBe('database')
  })

  it('maps file / web / connector enum values to their groups', () => {
    expect(getTypeGroup('file_upload')).toBe('file')
    expect(getTypeGroup('web_url')).toBe('web')
    expect(getTypeGroup('confluence')).toBe('integration')
    expect(getTypeGroup('sharepoint')).toBe('integration')
  })

  it('keeps the forward-compat dialect strings in the "database" group', () => {
    // `demoSources.ts` still uses 'postgresql' — sourceKindOf keeps it as DB.
    expect(getTypeGroup('postgresql')).toBe('database')
  })
})

describe('SourcesTable — "Database" type filter (FX8)', () => {
  it('shows the database row and hides the file_upload row when the filter is "Database"', async () => {
    const dbRow = makeSource({
      id: 'src-db',
      name: 'Sales replica DB',
      source_type: 'database',
    })
    const fileRow = makeSource({
      id: 'src-file',
      name: 'Q4 plan.pdf',
      source_type: 'file_upload',
    })
    renderTable([dbRow, fileRow])

    // Initially ("All") both rows are visible.
    expect(screen.getAllByText('Sales replica DB').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Q4 plan.pdf').length).toBeGreaterThan(0)

    // Click the "Database" toolbar chip.
    await userEvent.click(screen.getByRole('button', { name: 'Database' }))

    // DB row stays; file row disappears.
    expect(screen.getAllByText('Sales replica DB').length).toBeGreaterThan(0)
    expect(screen.queryByText('Q4 plan.pdf')).toBeNull()
  })

  it('shows the file_upload row and hides the database row when the filter is "Files"', async () => {
    const dbRow = makeSource({
      id: 'src-db',
      name: 'Sales replica DB',
      source_type: 'database',
    })
    const fileRow = makeSource({
      id: 'src-file',
      name: 'Q4 plan.pdf',
      source_type: 'file_upload',
    })
    renderTable([dbRow, fileRow])

    await userEvent.click(screen.getByRole('button', { name: 'Files' }))

    expect(screen.getAllByText('Q4 plan.pdf').length).toBeGreaterThan(0)
    expect(screen.queryByText('Sales replica DB')).toBeNull()
  })
})
