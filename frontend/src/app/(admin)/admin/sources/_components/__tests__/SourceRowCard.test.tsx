/**
 * FX8 — SourceRowCard DB-source affordances must key off the real
 * `source_type === 'database'` discriminator, not a fictional per-dialect set.
 *
 * Asserts the mobile card renders the DatabaseStudyStrip (and not the
 * IngestionStrip) for a `source_type === 'database'` row, exactly as it does
 * for the forward-compat `'postgresql'` value.
 */

import type { SourceListItem } from '@/lib/api/sources'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Stub the heavy children so this suite focuses on the strip-selection branch.
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

import { SourceRowCard } from '../SourceRowCard'

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
    source_mode: 'snapshot',
    ...overrides,
  }
}

describe('SourceRowCard — DB-source strip selection (FX8)', () => {
  it('renders the DatabaseStudyStrip for source_type === "database"', () => {
    render(
      <SourceRowCard
        source={makeSource({ source_type: 'database', source_mode: 'live' })}
        onDelete={() => {}}
      />
    )
    expect(screen.getByTestId('db-study-strip-stub')).toBeInTheDocument()
    expect(screen.queryByTestId('ingestion-strip-stub')).toBeNull()
  })

  it('renders the DatabaseStudyStrip for the forward-compat "postgresql" value', () => {
    render(
      <SourceRowCard
        source={makeSource({ source_type: 'postgresql', source_mode: 'live' })}
        onDelete={() => {}}
      />
    )
    expect(screen.getByTestId('db-study-strip-stub')).toBeInTheDocument()
    expect(screen.queryByTestId('ingestion-strip-stub')).toBeNull()
  })

  it('renders the IngestionStrip for a file source', () => {
    render(
      <SourceRowCard
        source={makeSource({ source_type: 'file_upload' })}
        onDelete={() => {}}
      />
    )
    expect(screen.getByTestId('ingestion-strip-stub')).toBeInTheDocument()
    expect(screen.queryByTestId('db-study-strip-stub')).toBeNull()
  })

  it('FX14: never renders the AI description, regardless of description_status', () => {
    const longDesc =
      'This is a very long AI-generated description that would otherwise consume the whole card and ruin the layout — FX14.'
    render(
      <SourceRowCard
        source={makeSource({
          source_type: 'file_upload',
          name: 'Acme Wiki',
          description: longDesc,
          description_status: 'ai_set',
          name_status: 'user_set',
        })}
        onDelete={() => {}}
      />
    )
    expect(screen.queryByText(longDesc)).toBeNull()
    expect(screen.queryByText('—')).toBeNull()
  })

  it('FX14: exposes the full name via the `title` attribute on the truncated title link', () => {
    const longName =
      'Extremely Long Source Name That Will Be Truncated On The Card But Discoverable On Hover'
    render(
      <SourceRowCard
        source={makeSource({
          source_type: 'file_upload',
          name: longName,
          name_status: 'user_set',
        })}
        onDelete={() => {}}
      />
    )
    const link = screen.getByTitle(longName)
    expect(link.tagName).toBe('A')
  })
})
