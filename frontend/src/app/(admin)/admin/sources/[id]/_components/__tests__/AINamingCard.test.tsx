/**
 * AINamingCard — Settings-tab AI naming assistant.
 *
 * Verifies:
 *   - Provenance copy adapts to name_status / description_status.
 *   - Regenerate description fills only `description` via onApply.
 *   - Regenerate both fills both fields via onApply.
 *   - Regenerate both opens a name-protection dialog when the current name
 *     is `user_set`; Continue confirms, Cancel aborts without firing.
 *   - History link opens the Sheet with the placeholder copy.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  AutoNameResponse,
  RefreshDescriptionResponse,
  SourceDetail,
} from '@/lib/api/sources'

const refreshDescriptionMock = vi.fn<(id: string) => Promise<RefreshDescriptionResponse>>()
const autoNameMock = vi.fn<(id: string) => Promise<AutoNameResponse>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    refreshDescriptionApi: (id: string) => refreshDescriptionMock(id),
    autoNameApi: (id: string) => autoNameMock(id),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { AINamingCard } from '../AINamingCard'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Engineering wiki',
    source_type: 'web_url',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: 'Wiki content',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-05-08T00:00:00Z',
    ...overrides,
  } satisfies SourceDetail
}

function renderCard(source: SourceDetail, onApply = vi.fn()): {
  onApply: ReturnType<typeof vi.fn>
} {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  render(<AINamingCard source={source} onApply={onApply} />, { wrapper: Wrapper })
  return { onApply }
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  refreshDescriptionMock.mockReset()
  autoNameMock.mockReset()
  refreshDescriptionMock.mockResolvedValue({
    proposed_description: 'New AI description.',
  })
  autoNameMock.mockResolvedValue({
    proposed_name: 'New AI name',
    proposed_description: 'New AI description.',
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AINamingCard — provenance lines', () => {
  it('renders "User-edited" when name_status === "user_set"', () => {
    renderCard(makeSource({ name_status: 'user_set' }))
    const line = screen.getByTestId('ai-naming-name-provenance')
    expect(line).toHaveAttribute('data-status', 'user_set')
    expect(line).toHaveTextContent(/user-edited/i)
  })

  it('renders "AI-written" when name_status === "ai_set"', () => {
    renderCard(makeSource({ name_status: 'ai_set' }))
    expect(screen.getByTestId('ai-naming-name-provenance')).toHaveTextContent(
      /ai-written/i
    )
  })

  it('renders "Naming…" shimmer when name_status === "pending_ai"', () => {
    renderCard(makeSource({ name_status: 'pending_ai' }))
    expect(screen.getByTestId('ai-naming-name-provenance')).toHaveTextContent(
      /naming…/i
    )
  })

  it('description provenance line follows the same rules', () => {
    renderCard(makeSource({ description_status: 'ai_set' }))
    expect(
      screen.getByTestId('ai-naming-description-provenance')
    ).toHaveTextContent(/ai-written/i)
  })
})

describe('AINamingCard — regenerate description (only)', () => {
  it('calls onApply with description-only payload after Accept', async () => {
    const user = userEvent.setup()
    const { onApply } = renderCard(makeSource())

    await user.click(screen.getByTestId('ai-naming-regenerate-description'))

    // Diff dialog opens.
    const accept = await screen.findByTestId('ai-naming-diff-accept')
    await user.click(accept)

    expect(onApply).toHaveBeenCalledTimes(1)
    expect(onApply).toHaveBeenCalledWith({
      description: 'New AI description.',
    })
    expect(refreshDescriptionMock).toHaveBeenCalledWith('src-1')
    expect(autoNameMock).not.toHaveBeenCalled()
  })

  it('Discard closes the dialog without calling onApply', async () => {
    const user = userEvent.setup()
    const { onApply } = renderCard(makeSource())

    await user.click(screen.getByTestId('ai-naming-regenerate-description'))
    const discard = await screen.findByTestId('ai-naming-diff-discard')
    await user.click(discard)

    expect(onApply).not.toHaveBeenCalled()
  })
})

describe('AINamingCard — regenerate both', () => {
  it('calls onApply with name AND description when current name is AI-set', async () => {
    const user = userEvent.setup()
    const { onApply } = renderCard(makeSource({ name_status: 'ai_set' }))

    await user.click(screen.getByTestId('ai-naming-regenerate-both'))

    // No name-protection dialog because the name was AI-written, not typed
    // by the admin. The diff dialog opens immediately.
    const accept = await screen.findByTestId('ai-naming-diff-accept')
    await user.click(accept)

    expect(onApply).toHaveBeenCalledWith({
      name: 'New AI name',
      description: 'New AI description.',
    })
    expect(autoNameMock).toHaveBeenCalledWith('src-1')
  })

  it('opens a name-protection dialog when the current name is "user_set"', async () => {
    const user = userEvent.setup()
    const { onApply } = renderCard(makeSource({ name_status: 'user_set' }))

    await user.click(screen.getByTestId('ai-naming-regenerate-both'))

    // Confirmation dialog should appear, NOT the diff yet.
    const confirm = await screen.findByTestId('ai-naming-confirm-regenerate-both')
    expect(confirm).toBeInTheDocument()
    expect(autoNameMock).not.toHaveBeenCalled()
    expect(onApply).not.toHaveBeenCalled()

    // Continue → fires auto-name.
    await user.click(screen.getByTestId('ai-naming-confirm-continue'))
    await waitFor(() => expect(autoNameMock).toHaveBeenCalledTimes(1))

    // Diff opens. Accept persists into onApply.
    const accept = await screen.findByTestId('ai-naming-diff-accept')
    await user.click(accept)

    expect(onApply).toHaveBeenCalledWith({
      name: 'New AI name',
      description: 'New AI description.',
    })
  })

  it('Cancel on the protection dialog aborts without firing autoName', async () => {
    const user = userEvent.setup()
    const { onApply } = renderCard(makeSource({ name_status: 'user_set' }))

    await user.click(screen.getByTestId('ai-naming-regenerate-both'))
    await screen.findByTestId('ai-naming-confirm-regenerate-both')

    const cancel = screen.getByRole('button', { name: /cancel/i })
    await user.click(cancel)

    expect(autoNameMock).not.toHaveBeenCalled()
    expect(onApply).not.toHaveBeenCalled()
  })
})

describe('AINamingCard — history link', () => {
  it('opens a Sheet with the placeholder copy when the History link is clicked', async () => {
    const user = userEvent.setup()
    renderCard(makeSource())

    await user.click(screen.getByTestId('ai-naming-history-link'))

    const sheet = await screen.findByTestId('ai-naming-history-sheet')
    expect(sheet).toHaveTextContent(/history view coming soon/i)
  })
})
