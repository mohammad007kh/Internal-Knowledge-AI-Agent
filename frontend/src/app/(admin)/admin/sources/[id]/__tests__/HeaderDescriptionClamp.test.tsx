/**
 * FX27 — clamp the AI/admin-authored description rendered at the top of the
 * source-detail page header to a 2-line preview. The full description must
 * still be:
 *
 *   1. Available on the Settings tab in the editable textarea (uncapped).
 *   2. Exposed on hover via `title=` on the truncated `<p>`.
 *   3. Read in full by screen readers via a visually-hidden sibling span.
 *
 * Also locks down the pending-AI state: when `description_status === 'pending_ai'`
 * and no description is set yet, a shimmer pill renders in place of the prose.
 */
import type {
  PaginatedDocuments,
  PaginatedSyncJobs,
  SourceDetail,
  SourceStats,
  SyncJob,
  TestConnectionResponse,
  UpdateSourceRequest,
} from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const updateSourceMock =
  vi.fn<(id: string, body: UpdateSourceRequest) => Promise<SourceDetail>>()
const triggerSyncMock = vi.fn<(id: string) => Promise<SyncJob>>()
const testConnectionMock = vi.fn<(id: string) => Promise<TestConnectionResponse>>()
const listSyncJobsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedSyncJobs>>()
const listDocumentsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedDocuments>>()
const getSourceMock = vi.fn<(id: string) => Promise<SourceDetail>>()
const getStatsMock = vi.fn<(id: string) => Promise<SourceStats>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    getSourceApi: (id: string) => getSourceMock(id),
    getSourceStatsApi: (id: string) => getStatsMock(id),
    listSyncJobsApi: (id: string, limit?: number, offset?: number) =>
      listSyncJobsMock(id, limit, offset),
    listSourceDocumentsApi: (id: string, limit?: number, offset?: number) =>
      listDocumentsMock(id, limit, offset),
    updateSourceApi: (id: string, body: UpdateSourceRequest) =>
      updateSourceMock(id, body),
    triggerSyncApi: (id: string) => triggerSyncMock(id),
    testConnectionApi: (id: string) => testConnectionMock(id),
    deleteSourceApi: vi.fn(),
    refreshDescriptionApi: vi.fn(),
    autoNameApi: vi.fn(),
    listSourcePermissionsApi: vi.fn(async () => [] as string[]),
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({ id: 'src-1' }),
  usePathname: () => '/admin/sources/src-1',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import SourceDetailPage from '../page'

const LONG_DESCRIPTION =
  'This knowledge source contains the complete internal engineering handbook ' +
  'for the platform, including service runbooks, on-call rotations, postmortems, ' +
  'architecture decision records, infrastructure topology diagrams, deployment ' +
  'pipelines, incident response procedures, security policies, and the canonical ' +
  'glossary of internal terminology used across all engineering teams. Use this ' +
  'source when you need authoritative answers about how the platform works ' +
  'internally rather than how external integrations behave.'

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Engineering Handbook',
    source_type: 'web_url',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: LONG_DESCRIPTION,
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-01-01T00:00:00Z',
    owner_email: null,
    schema_summary: null,
    ...overrides,
  } satisfies SourceDetail
}

function renderPage(): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<SourceDetailPage />, { wrapper: Wrapper })
}

beforeEach(() => {
  updateSourceMock.mockReset()
  triggerSyncMock.mockReset()
  testConnectionMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()
  getSourceMock.mockReset()
  getStatsMock.mockReset()

  getSourceMock.mockResolvedValue(makeSource())
  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('SourceDetailPage header — FX27 description clamp', () => {
  it('applies the line-clamp + max-width classes and exposes the full text via `title=`', async () => {
    renderPage()

    const p = await screen.findByTestId('header-description')
    expect(p.tagName).toBe('P')
    // Tailwind utility classes lock the visual contract.
    expect(p).toHaveClass('line-clamp-2')
    expect(p).toHaveClass('max-w-[640px]')
    expect(p).toHaveClass('text-sm')
    // Hover reveal carries the FULL description verbatim — not the truncated version.
    expect(p).toHaveAttribute('title', LONG_DESCRIPTION)
    // The visible <p> is marked aria-hidden so screen readers don't read the
    // truncated copy; the full text lives in a sibling sr-only span.
    expect(p).toHaveAttribute('aria-hidden', 'true')
  })

  it('renders the FULL description in a screen-reader-only sibling span (accessibility)', async () => {
    renderPage()

    const p = await screen.findByTestId('header-description')
    // The full description should appear somewhere else in the DOM with the
    // `sr-only` class — that's what assistive tech actually announces.
    const srSiblings = document.querySelectorAll('.sr-only')
    const matched = Array.from(srSiblings).some(
      (el) => el.textContent === LONG_DESCRIPTION
    )
    expect(matched).toBe(true)
    // And the sr-only sibling is in fact a sibling of the truncated <p> (same parent).
    const parent = p.parentElement
    expect(parent).not.toBeNull()
    const siblingMatched = Array.from(parent?.querySelectorAll('.sr-only') ?? []).some(
      (el) => el.textContent === LONG_DESCRIPTION
    )
    expect(siblingMatched).toBe(true)
  })

  it('renders nothing in the header description slot when description is null', async () => {
    getSourceMock.mockResolvedValue(makeSource({ description: null }))
    renderPage()
    // Wait for the header `<h1>` so we know the page is hydrated.
    await screen.findByRole('heading', { level: 1, name: 'Engineering Handbook' })
    expect(screen.queryByTestId('header-description')).toBeNull()
    expect(screen.queryByTestId('pending-description-pill')).toBeNull()
  })

  it('renders the shimmer pill when description_status === "pending_ai" and description is empty', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ description: null, description_status: 'pending_ai' })
    )
    renderPage()

    const pill = await screen.findByTestId('pending-description-pill')
    expect(pill).toHaveClass('animate-pulse')
    expect(pill).toHaveAttribute('aria-label', 'Drafting description in progress')
    // The clamped <p> must NOT also render when the pill is showing.
    expect(screen.queryByTestId('header-description')).toBeNull()
  })

  it('still shows the clamped description (not the pill) when status === "pending_ai" but description is already present', async () => {
    // Regeneration case: a description already exists; the AI is rewriting it.
    // We should NOT hide the existing prose under a shimmer — the admin still
    // needs to read what they have.
    getSourceMock.mockResolvedValue(
      makeSource({ description_status: 'pending_ai' })
    )
    renderPage()

    expect(await screen.findByTestId('header-description')).toBeInTheDocument()
    expect(screen.queryByTestId('pending-description-pill')).toBeNull()
  })

  it('Settings tab textarea still shows the FULL description (unclamped, editable)', async () => {
    renderPage()
    const user = userEvent.setup()
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument()
    )
    await user.click(screen.getByRole('tab', { name: 'Settings' }))

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const textarea = within(form).getByLabelText('Description') as HTMLTextAreaElement
    // Full, untruncated text is in the textarea value.
    expect(textarea.value).toBe(LONG_DESCRIPTION)
    // And the textarea itself does NOT carry the line-clamp class — admin
    // needs to scroll/edit the full description here.
    expect(textarea).not.toHaveClass('line-clamp-2')
  })
})
