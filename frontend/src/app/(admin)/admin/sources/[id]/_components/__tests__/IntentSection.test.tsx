/**
 * IntentSection — source-intent review surface (004-agentic-pipeline T-025).
 *
 * Verifies:
 *   - Renders the loaded intent fields (purpose + example questions + out of
 *     scope) for an `ai_set` source, with the FR-002 review-to-activate badge.
 *   - `user_set` shows the "Reviewed" badge.
 *   - Save calls PUT (`putIntentApi`) and the badge flips to "Reviewed" when
 *     the server returns `user_set`.
 *   - "Regenerate draft" calls propose; a 409 surfaces a Sonner toast.
 *   - Zod blocks a 6th example question (cap = 5) and a 501-char purpose
 *     (cap = 500) client-side — no PUT is fired.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceIntent, SourceIntentUpdate } from '@/lib/api/sources'

const getIntentMock = vi.fn<(id: string) => Promise<SourceIntent>>()
const putIntentMock = vi.fn<(id: string, body: SourceIntentUpdate) => Promise<SourceIntent>>()
const proposeIntentMock = vi.fn<(id: string) => Promise<void>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    getIntentApi: (id: string) => getIntentMock(id),
    putIntentApi: (id: string, body: SourceIntentUpdate) => putIntentMock(id, body),
    proposeIntentApi: (id: string) => proposeIntentMock(id),
  }
})

const toastErrorMock = vi.fn()
const toastSuccessMock = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccessMock(...args),
    error: (...args: unknown[]) => toastErrorMock(...args),
  },
}))

import { IntentProposalConflictError } from '@/lib/api/sources'
import { IntentSection } from '../IntentSection'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeIntent(overrides: Partial<SourceIntent> = {}): SourceIntent {
  return {
    purpose: 'Answers questions about the engineering wiki.',
    example_questions: ['How do I deploy?', 'Where are the runbooks?'],
    out_of_scope: ['Payroll data'],
    cross_source_hints: null,
    intent_status: 'ai_set',
    intent_updated_at: '2026-05-08T00:00:00Z',
    ...overrides,
  }
}

function renderSection(sourceId = 'src-1') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<IntentSection sourceId={sourceId} />, { wrapper: Wrapper })
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  getIntentMock.mockReset()
  putIntentMock.mockReset()
  proposeIntentMock.mockReset()
  toastErrorMock.mockReset()
  toastSuccessMock.mockReset()

  getIntentMock.mockResolvedValue(makeIntent())
  putIntentMock.mockImplementation(async (_id, body) =>
    makeIntent({
      purpose: body.purpose ?? null,
      example_questions: body.example_questions ?? null,
      out_of_scope: body.out_of_scope ?? null,
      intent_status: 'user_set',
    })
  )
  proposeIntentMock.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IntentSection — render + badge', () => {
  it('renders the loaded intent fields with the ai_set review-to-activate badge', async () => {
    renderSection()

    // The badge renders synchronously with the default `pending_ai` and flips
    // once the intent query resolves — wait for the loaded status.
    const badge = screen.getByTestId('intent-status-badge')
    await waitFor(() => expect(badge).toHaveAttribute('data-status', 'ai_set'))
    expect(badge).toHaveTextContent('AI-proposed — review to activate declines')

    // Purpose hydrated into the textarea.
    expect(await screen.findByLabelText('Purpose')).toHaveValue(
      'Answers questions about the engineering wiki.'
    )

    // Example questions + out-of-scope rows rendered from the fetched data.
    expect(screen.getByDisplayValue('How do I deploy?')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Where are the runbooks?')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Payroll data')).toBeInTheDocument()
  })

  it('shows the "Reviewed" badge for a user_set source', async () => {
    getIntentMock.mockResolvedValue(makeIntent({ intent_status: 'user_set' }))
    renderSection()

    const badge = screen.getByTestId('intent-status-badge')
    await waitFor(() => expect(badge).toHaveAttribute('data-status', 'user_set'))
    expect(badge).toHaveTextContent('Reviewed')
  })

  it('shows the "Draft pending" badge for a pending_ai source', async () => {
    getIntentMock.mockResolvedValue(makeIntent({ intent_status: 'pending_ai' }))
    renderSection()

    const badge = screen.getByTestId('intent-status-badge')
    await waitFor(() => expect(badge).toHaveAttribute('data-status', 'pending_ai'))
    expect(badge).toHaveTextContent('Draft pending')
  })
})

describe('IntentSection — Save (PUT → user_set)', () => {
  it('calls PUT and flips the badge to "Reviewed" on success', async () => {
    const user = userEvent.setup()
    renderSection()

    // Dirty the form so Save enables (Save is disabled when pristine).
    const purpose = await screen.findByLabelText('Purpose')
    await user.type(purpose, ' Updated.')

    const save = screen.getByTestId('intent-save')
    await waitFor(() => expect(save).not.toBeDisabled())
    await user.click(save)

    await waitFor(() => expect(putIntentMock).toHaveBeenCalledTimes(1))
    expect(putIntentMock.mock.calls[0]?.[0]).toBe('src-1')

    // Server returned user_set → badge updates.
    await waitFor(() =>
      expect(screen.getByTestId('intent-status-badge')).toHaveTextContent('Reviewed')
    )

    // FIX 4(b) — success toast copy is asserted verbatim.
    expect(toastSuccessMock).toHaveBeenCalledWith('Intent reviewed and saved.')
  })

  it('surfaces a server 422 inline (intent-server-error) when PUT rejects', async () => {
    // FIX 4(d) — the interceptor flattens problem+json to a plain Error; the
    // component shows its message inline rather than a structured field map.
    putIntentMock.mockRejectedValue(new Error('Purpose contains disallowed content.'))
    const user = userEvent.setup()
    renderSection()

    const purpose = await screen.findByLabelText('Purpose')
    await user.type(purpose, ' Updated.')

    const save = screen.getByTestId('intent-save')
    await waitFor(() => expect(save).not.toBeDisabled())
    await user.click(save)

    const inline = await screen.findByTestId('intent-server-error')
    expect(inline).toHaveTextContent('Purpose contains disallowed content.')
    // Inline path, not a toast.
    expect(toastSuccessMock).not.toHaveBeenCalled()
  })
})

describe('IntentSection — Regenerate draft', () => {
  it('calls propose on click', async () => {
    const user = userEvent.setup()
    renderSection()

    await user.click(await screen.findByTestId('intent-regenerate'))
    await waitFor(() => expect(proposeIntentMock).toHaveBeenCalledWith('src-1'))

    // FIX 4(c) — success toast copy is asserted verbatim.
    await waitFor(() =>
      expect(toastSuccessMock).toHaveBeenCalledWith('Regenerating the AI draft…')
    )
  })

  it('surfaces a Sonner toast when propose returns 409', async () => {
    proposeIntentMock.mockRejectedValue(new IntentProposalConflictError())
    const user = userEvent.setup()
    renderSection()

    await user.click(await screen.findByTestId('intent-regenerate'))

    await waitFor(() =>
      expect(toastErrorMock).toHaveBeenCalledWith('A study or proposal is already running.')
    )
  })

  it('disables Regenerate for a user_set source', async () => {
    getIntentMock.mockResolvedValue(makeIntent({ intent_status: 'user_set' }))
    renderSection()

    await waitFor(() => expect(screen.getByTestId('intent-regenerate')).toBeDisabled())
    expect(proposeIntentMock).not.toHaveBeenCalled()
  })
})

describe('IntentSection — Zod caps block invalid submits client-side', () => {
  it('blocks a 6th example question (cap = 5) — the Add button is disabled at cap', async () => {
    getIntentMock.mockResolvedValue(
      makeIntent({
        example_questions: ['q1', 'q2', 'q3', 'q4', 'q5'],
      })
    )
    renderSection()

    // At cap → the Add button is disabled, so a 6th can't be added.
    const add = await screen.findByTestId('intent-example_questions-add')
    await waitFor(() => expect(add).toBeDisabled())
  })

  it('blocks a 501-char purpose (cap = 500) — Zod rejects, no PUT fired', async () => {
    const user = userEvent.setup()
    renderSection()

    const purpose = await screen.findByLabelText('Purpose')
    // The textarea's maxLength clamps *typed* input; a programmatic change
    // event (as a paste would produce in the browser) bypasses it, letting us
    // exercise the Zod guard. RHF picks the value up off the change event.
    fireEvent.change(purpose, { target: { value: 'x'.repeat(501) } })

    const save = screen.getByTestId('intent-save')
    await waitFor(() => expect(save).not.toBeDisabled())
    await user.click(save)

    // Zod rejects → inline error shown, no PUT.
    await waitFor(() => expect(screen.getByText(/500 characters or fewer/i)).toBeInTheDocument())
    expect(putIntentMock).not.toHaveBeenCalled()
  })
})

describe('IntentSection — list cap boundaries (Add button gating)', () => {
  it('FIX 4(e) — out-of-scope: 10 items disables Add, 9 keeps it enabled', async () => {
    // 9 items → below cap (10) → Add enabled.
    getIntentMock.mockResolvedValue(
      makeIntent({
        out_of_scope: ['o1', 'o2', 'o3', 'o4', 'o5', 'o6', 'o7', 'o8', 'o9'],
      })
    )
    const { unmount } = renderSection()

    const addAt9 = await screen.findByTestId('intent-out_of_scope-add')
    await waitFor(() => expect(addAt9).not.toBeDisabled())
    unmount()

    // 10 items → at cap → Add disabled.
    getIntentMock.mockResolvedValue(
      makeIntent({
        out_of_scope: ['o1', 'o2', 'o3', 'o4', 'o5', 'o6', 'o7', 'o8', 'o9', 'o10'],
      })
    )
    renderSection()

    const addAt10 = await screen.findByTestId('intent-out_of_scope-add')
    await waitFor(() => expect(addAt10).toBeDisabled())
  })

  it('FIX 4(f) — questions: 4 items keeps Add enabled; adding one disables it at 5', async () => {
    getIntentMock.mockResolvedValue(
      makeIntent({ example_questions: ['q1', 'q2', 'q3', 'q4'] })
    )
    const user = userEvent.setup()
    renderSection()

    const add = await screen.findByTestId('intent-example_questions-add')
    // 4 items → below cap (5) → enabled.
    await waitFor(() => expect(add).not.toBeDisabled())

    // Adding the 5th hits the cap → Add disables.
    await user.click(add)
    await waitFor(() => expect(add).toBeDisabled())
  })
})
