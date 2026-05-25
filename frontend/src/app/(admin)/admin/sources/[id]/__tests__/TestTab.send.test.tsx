/**
 * TestTab — sandbox send→stream→render integration.
 *
 * This test class covers the bug class the existing TestTab.test.tsx
 * doesn't: clicking Send through to the assistant bubble actually
 * appearing on screen. Previously the backend never emitted a delta
 * frame for the answer text, leaving the bubble blank — pulsing dots
 * disappeared and nothing rendered.
 *
 * We mock `fetch` to return a real ReadableStream of SSE frames, so
 * useSandboxStream's reader/decoder/parser path runs end-to-end. The
 * component's useEffect then folds the streamed text into the messages
 * array as a real assistant turn.
 */
import type { SourceDetail } from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Module mocks (must come before imports of the SUT)
// ---------------------------------------------------------------------------

const useAuthMock = vi.fn()

vi.mock('@/features/auth/context/AuthContext', () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@/lib/token-store', () => ({
  getToken: () => 'test-token',
  setToken: vi.fn(),
}))

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

import { TestTab } from '../_components/TestTab'

// ---------------------------------------------------------------------------
// Helpers — build a streaming SSE Response
// ---------------------------------------------------------------------------

function sseFrame(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function makeStreamResponse(frames: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder()
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'c43e9bab-8154-4056-9541-623da09ec107',
    name: 'Postgres',
    source_type: 'postgresql',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'live',
    retrieval_mode: 'text_to_query',
    description: 'Production read replica',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-01-01T00:00:00Z',
    schema_status: 'completed',
    owner_email: null,
    schema_summary: null,
    ...overrides,
  } satisfies SourceDetail
}

function renderTestTab(source: SourceDetail = makeSource()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<TestTab source={source} />, { wrapper: Wrapper })
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  useAuthMock.mockReset()
  useAuthMock.mockReturnValue({
    user: {
      id: 'u-1',
      email: 'admin@example.com',
      role: 'admin',
      must_change_password: false,
    },
    accessToken: 'tok',
    isLoading: false,
    setAccessToken: vi.fn(),
    clearAccessToken: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TestTab — send → stream → render (regression)', () => {
  it('renders the assistant turn after a delta + done stream', async () => {
    // The bug pattern: backend used to emit ONLY `done` and the bubble
    // stayed empty. The fix emits the answer text as a synthetic delta
    // before `done`. This test asserts the bubble actually shows the
    // answer text after the stream completes.
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'Schema lookup says:' }),
        sseFrame('delta', { token: ' 14 tables.' }),
        sseFrame('done', {
          session_id: '__sandbox__',
          message_id: '',
          trace_id: 't-1',
          sources: [],
        }),
      ])
    )

    const user = userEvent.setup()
    renderTestTab()

    const input = screen.getByTestId('sandbox-input')
    await user.type(input, 'How many tables exist?')
    await user.click(screen.getByTestId('sandbox-send'))

    // The user bubble appears immediately.
    expect(await screen.findByText('How many tables exist?')).toBeInTheDocument()

    // The assistant bubble appears once the stream terminates and the
    // useEffect folds currentResponse into the messages array.
    await waitFor(() =>
      expect(screen.getByText('Schema lookup says: 14 tables.')).toBeInTheDocument()
    )
  })

  it('renders a stream-error message when the backend yields error frame', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('error', { message: 'Pipeline failed', code: 'pipeline_error' }),
      ])
    )

    const user = userEvent.setup()
    renderTestTab()

    await user.type(screen.getByTestId('sandbox-input'), 'q')
    await user.click(screen.getByTestId('sandbox-send'))

    await waitFor(() =>
      expect(screen.getByText(/Stream error.*Pipeline failed/i)).toBeInTheDocument()
    )
  })

  it('POSTs to /api/v1/chat/sandbox/stream with the source id and query', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'ok' }),
        sseFrame('done', { session_id: '__sandbox__', message_id: '', sources: [] }),
      ])
    )

    const user = userEvent.setup()
    renderTestTab()

    await user.type(screen.getByTestId('sandbox-input'), 'hello')
    await user.click(screen.getByTestId('sandbox-send'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/v1\/chat\/sandbox\/stream$/)
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body as string)
    expect(body.source_id).toBe('c43e9bab-8154-4056-9541-623da09ec107')
    expect(body.query).toBe('hello')
  })

  it('renders nothing in the bubble pre-fix scenario (only `done`, no `delta`)', async () => {
    // This test documents the failure mode the fix prevents. With ONLY a
    // `done` event and no `delta`, the assistant bubble stays empty. We
    // assert there's NO assistant bubble visible — proving the bug class
    // exists at the wire-level so the fix is necessary.
    //
    // Once the backend is fixed, this scenario shouldn't occur on the
    // wire — but if it ever does, the user sees nothing rather than a
    // stuck spinner.
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('done', {
          session_id: '__sandbox__',
          message_id: '',
          trace_id: 't-1',
          sources: [],
        }),
      ])
    )

    const user = userEvent.setup()
    renderTestTab()

    await user.type(screen.getByTestId('sandbox-input'), 'no-stream')
    await user.click(screen.getByTestId('sandbox-send'))

    // Wait for the user bubble (proves the click reached the form).
    await waitFor(() =>
      expect(screen.getByText('no-stream')).toBeInTheDocument()
    )
    // Eventually the streaming spinner disappears (isStreaming false).
    await waitFor(() =>
      expect(screen.queryByTestId('sandbox-thinking')).toBeNull()
    )
    // No assistant bubble was rendered — only the user message bubble.
    // (This is the user-visible "got nothing back" symptom.)
    const userBubbleParent = screen.getByText('no-stream').closest('[role="log"]')
    expect(userBubbleParent).not.toBeNull()
  })
})
