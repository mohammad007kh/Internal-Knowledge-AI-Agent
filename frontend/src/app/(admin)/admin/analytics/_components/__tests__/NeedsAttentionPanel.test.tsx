import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { NeedsAttentionItem } from '@/lib/api/analytics'
import { NeedsAttentionPanel } from '../NeedsAttentionPanel'

// next/navigation is mocked globally in src/test/setup.ts; next/link works
// directly in jsdom.

function item(overrides: Partial<NeedsAttentionItem> = {}): NeedsAttentionItem {
  return {
    source_id: '11111111-2222-3333-4444-555555555555',
    name: 'Prod Postgres',
    kind: 'connection',
    detail: 'connection timed out after 30s',
    ...overrides,
  }
}

describe('NeedsAttentionPanel', () => {
  it('renders a row per item with a link to the source detail page', () => {
    const data: NeedsAttentionItem[] = [
      item({ source_id: 'aaaa1111-0000-0000-0000-000000000001', name: 'Prod DB', kind: 'connection' }),
      item({
        source_id: 'aaaa1111-0000-0000-0000-000000000002',
        name: 'Internal Wiki',
        kind: 'sync',
        detail: 'HTTP 404',
      }),
      item({
        source_id: 'aaaa1111-0000-0000-0000-000000000003',
        name: 'Analytics DB',
        kind: 'study',
        detail: 'COLUMNS',
      }),
    ]
    render(<NeedsAttentionPanel data={data} loading={false} />)

    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(3)
    expect(links[0]).toHaveAttribute('href', '/admin/sources/aaaa1111-0000-0000-0000-000000000001')
    expect(within(links[0]).getByText('Prod DB')).toBeInTheDocument()
    expect(within(links[0]).getByText('Connection')).toBeInTheDocument()
    expect(within(links[1]).getByText('Internal Wiki')).toBeInTheDocument()
    expect(within(links[1]).getByText('Sync')).toBeInTheDocument()
    expect(within(links[2]).getByText('Analytics DB')).toBeInTheDocument()
    expect(within(links[2]).getByText('Study')).toBeInTheDocument()
    // The count badge in the header.
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows the healthy empty state when there are no items', () => {
    render(<NeedsAttentionPanel data={[]} loading={false} />)
    expect(screen.getByText('All sources healthy ✓')).toBeInTheDocument()
    expect(screen.queryAllByRole('link')).toHaveLength(0)
  })

  it('shows skeletons while loading', () => {
    const { container } = render(<NeedsAttentionPanel data={undefined} loading />)
    // Skeleton renders an animate-pulse div.
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
    expect(screen.queryByText('All sources healthy ✓')).not.toBeInTheDocument()
  })

  it('falls back to a generic detail when detail is null', () => {
    render(<NeedsAttentionPanel data={[item({ detail: null })]} loading={false} />)
    expect(screen.getByText('See source for details')).toBeInTheDocument()
  })
})
