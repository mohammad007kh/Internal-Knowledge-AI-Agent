import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { type ReactNode, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChat } from '../useChat'

vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}))

// Spy on the session-selection context so we can assert WHEN navigation
// (setSessionId → router.replace) fires. The real default context is a no-op,
// which is why the lazy-create stream-abort bug was invisible to these tests.
const { setSessionIdSpy } = vi.hoisted(() => ({ setSessionIdSpy: vi.fn() }))
vi.mock('../SelectedSessionContext', () => ({
  useSelectedSession: () => ({
    sessionId: null,
    setSessionId: setSessionIdSpy,
    registerAbortStream: () => () => {},
    abortStream: () => {},
  }),
}))

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

/**
 * A ReadableStream that never closes — lets us assert state during the
 * "stream is in flight" window without racing against a synchronous end.
 */
function makePendingStream(): {
  body: ReadableStream<Uint8Array>
  push: (chunk: string) => void
  close: () => void
} {
  const encoder = new TextEncoder()
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
    },
  })
  return {
    body,
    push: (chunk: string) => controllerRef?.enqueue(encoder.encode(chunk)),
    close: () => controllerRef?.close(),
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

/**
 * Variant of {@link wrapper} that lets the test pre-seed the QueryClient with
 * cached `['chat-sessions']` data. We need to share the same client between
 * the hook render and the post-stream assertions, so the test owns the
 * client and passes it through.
 */
function makeWrapperWithClient(client: QueryClient) {
  return function Wrapped({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children)
  }
}

describe('useChat', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setSessionIdSpy.mockClear()
  })

  // Regression (lazy-create stream abort): the backend emits `session_created`
  // as the FIRST SSE frame. If the hook navigates (`setSessionId` → router.replace
  // to the `/chat/[id]` segment) on THAT frame, the `<ChatLayout>` that owns the
  // stream unmounts mid-stream and its unmount cleanup aborts the in-flight fetch
  // → the assistant answer never streams. Navigation MUST be deferred until the
  // stream has finished (a real `done`), by which point the AbortController is
  // already settled so the remount is harmless.
  it('does NOT navigate on session_created; navigates only after `done` (lazy-create stream-abort fix)', async () => {
    const pending = makePendingStream()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: pending.body }))

    const { result } = renderHook(() => useChat({ sessionId: null }), {
      wrapper: makeWrapperWithClient(
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      ),
    })

    await act(async () => {
      result.current.send('Hello world')
    })

    // session_created arrives FIRST — navigation must NOT fire yet (stream is live).
    await act(async () => {
      pending.push('event: session_created\ndata: {"session_id":"new-id-1"}\n\n')
    })
    expect(setSessionIdSpy).not.toHaveBeenCalled()

    // Tokens stream in — still no navigation.
    await act(async () => {
      pending.push('event: delta\ndata: {"token":"Hi"}\n\n')
    })
    expect(setSessionIdSpy).not.toHaveBeenCalled()

    // `done` lands and the stream closes — NOW navigation fires (controller settled).
    await act(async () => {
      pending.push('event: done\ndata: {"message_id":"m1"}\n\n')
      pending.close()
    })
    await waitFor(() => {
      expect(setSessionIdSpy).toHaveBeenCalledWith('new-id-1', { replace: true })
    })
  })

  // Orphan-session safety: while the URL still reads `/chat` (navigation deferred),
  // a SECOND send must target the freshly-minted id pinned on `session_created`,
  // NOT the `'new'` sentinel again (which would create a second orphan session).
  it('targets the real id (not the `new` sentinel) on a second send after session_created', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: pending.body })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChat({ sessionId: null }), {
      wrapper: makeWrapperWithClient(
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      ),
    })

    await act(async () => {
      result.current.send('first')
    })
    expect(fetchMock.mock.calls[0]?.[0]).toMatch(/\/sessions\/new\/messages$/)

    // Real id announced (but navigation deferred — URL/prop still null).
    await act(async () => {
      pending.push('event: session_created\ndata: {"session_id":"real-id-9"}\n\n')
    })

    // A second send (e.g. fast follow-up / retry) must hit the real session.
    await act(async () => {
      result.current.send('second')
    })
    expect(fetchMock.mock.calls[1]?.[0]).toMatch(/\/sessions\/real-id-9\/messages$/)
  })

  // Regression (HIGH, caught in review): after a first turn that ends in a
  // NON-navigating terminal (clarification/guardrail/error → stays on `/chat`),
  // the lazy-create pin still points at the just-created session. Starting a
  // fresh chat must clear that pin, or the next first message silently posts
  // into the previous (abandoned) session.
  it('clears the lazy-create pin on explicit new-chat so a fresh chat is not routed to the prior session', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: pending.body })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useChat({ sessionId: null }), {
      wrapper: makeWrapperWithClient(
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      ),
    })

    // First turn: session A is created, then the turn ends in a clarification
    // (no `done` → no navigation → URL stays `/chat`, pin = sess-A).
    await act(async () => {
      result.current.send('first')
    })
    await act(async () => {
      pending.push('event: session_created\ndata: {"session_id":"sess-A"}\n\n')
      pending.push('event: clarification\ndata: {"question":"which source?"}\n\n')
      pending.close()
    })

    // User explicitly starts a new chat.
    await act(async () => {
      result.current.resetLazyCreate()
    })

    // The brand-new first message MUST hit the `'new'` sentinel, not sess-A.
    await act(async () => {
      result.current.send('totally different topic')
    })
    expect(fetchMock.mock.calls.at(-1)?.[0]).toMatch(/\/sessions\/new\/messages$/)
  })

  it('sets isStreaming to true after send and false after done event', async () => {
    const sseBody =
      'event: token\ndata: {"token":"Hi"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), {
      wrapper,
    })

    expect(result.current.isStreaming).toBe(false)

    await act(async () => {
      result.current.send('Hello')
    })

    // After the stream completes, isStreaming should be false
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.isPending).toBe(false)
  })

  it('surfaces clarification options + allow_free_text from the clarification frame (T-082)', async () => {
    const sseBody =
      'event: clarification\n' +
      'data: {"question":"Which source?","options":[{"id":"src-1","label":"Q4 Financials","recommended":true},{"id":"src-2","label":"Board Notes"}],"allow_free_text":false}\n\n'

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseBody]) }))

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), { wrapper })

    await act(async () => {
      result.current.send('ambiguous question')
    })

    await waitFor(() => {
      expect(result.current.clarification).not.toBeNull()
    })
    expect(result.current.clarification?.question).toBe('Which source?')
    expect(result.current.clarification?.options?.map((o) => o.id)).toEqual(['src-1', 'src-2'])
    expect(result.current.clarification?.options?.[0].recommended).toBe(true)
    expect(result.current.clarification?.allowFreeText).toBe(false)
  })

  it('defaults clarification to no options + free-text allowed when the frame omits them', async () => {
    const sseBody = 'event: clarification\ndata: {"question":"Say more?"}\n\n'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseBody]) }))

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), { wrapper })
    await act(async () => {
      result.current.send('vague')
    })

    await waitFor(() => {
      expect(result.current.clarification).not.toBeNull()
    })
    expect(result.current.clarification?.options).toBeNull()
    expect(result.current.clarification?.allowFreeText).toBe(true)
  })

  it('unlocks textarea and shows error toast when stream closes without `done`', async () => {
    // SSE body that emits a token but never a terminal frame (no `done`,
    // no `error`, no `clarification`, no `guardrail_blocked`). The reader
    // closes cleanly — exactly the failure mode where the backend
    // bare-excepts a NotNullViolation mid-flight.
    const sseBody = 'event: delta\ndata: {"token":"partial"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const { toast } = await import('sonner')
    const errorSpy = toast.error as ReturnType<typeof vi.fn>
    errorSpy.mockClear()

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), {
      wrapper,
    })

    await act(async () => {
      result.current.send('hi')
    })

    // Textarea must unlock — `isPending` controls the disabled state.
    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
    })
    expect(result.current.isStreaming).toBe(false)
    // Optimistic user bubble must be cleared.
    expect(result.current.optimisticMessages).toEqual([])
    // An error toast must surface so the user knows something went wrong.
    expect(errorSpy).toHaveBeenCalled()
  })

  // Regression: when the auto-create-on-send flow lands a freshly-created
  // session id (sessionId transitions null → "new-1"), the abort-on-switch
  // cleanup must NOT abort the just-started stream. Before the fix, the
  // cleanup fired unconditionally, cancelled the AbortController of the
  // in-flight send, and called clearOptimistic — making the typed message
  // vanish and the chat surface "reset" to the empty state.
  it('does not clear optimistic bubble or isPending when sessionId transitions null → new id during a send', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: pending.body,
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useChat({ sessionId }),
      { wrapper, initialProps: { sessionId: null as string | null } }
    )

    // Auto-create-on-send: ChatLayout awaits the create mutation, gets
    // "new-1" back, and immediately calls send(text, "new-1") with the
    // override so the closure does not silently drop on the stale null.
    await act(async () => {
      result.current.send('Hello world', 'new-1')
    })

    expect(result.current.optimisticMessages).toHaveLength(1)
    expect(result.current.optimisticMessages[0]?.content).toBe('Hello world')
    expect(result.current.isPending).toBe(true)

    // ChatLayout's setSessionId(newId) propagates through React state,
    // re-rendering useChat with sessionId="new-1". Pre-fix this fired the
    // cleanup of the previous (sessionId=null) effect → abort() →
    // clearOptimistic + setIsPending(false), making the bubble flash and
    // disappear. Post-fix the cleanup checks the captured sessionId and
    // skips the abort when it was null.
    await act(async () => {
      rerender({ sessionId: 'new-1' })
    })

    expect(result.current.optimisticMessages).toHaveLength(1)
    expect(result.current.optimisticMessages[0]?.content).toBe('Hello world')
    expect(result.current.isPending).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const signal = fetchMock.mock.calls[0]?.[1]?.signal as AbortSignal | undefined
    expect(signal?.aborted).toBe(false)

    await act(async () => {
      pending.push('event: done\ndata: {"message_id":"m1"}\n\n')
      pending.close()
    })
  })

  // Sanity: a real session SWITCH (e.g. user picks another session from the
  // sidebar) must still abort the in-flight stream — the fix above only
  // skips the null → x transition.
  it('does abort the in-flight stream when switching from one real session to another', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: pending.body,
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useChat({ sessionId }),
      { wrapper, initialProps: { sessionId: 'session-a' as string | null } }
    )

    await act(async () => {
      result.current.send('Hello')
    })
    expect(result.current.isPending).toBe(true)

    await act(async () => {
      rerender({ sessionId: 'session-b' })
    })

    const signal = fetchMock.mock.calls[0]?.[1]?.signal as AbortSignal | undefined
    expect(signal?.aborted).toBe(true)
    expect(result.current.optimisticMessages).toHaveLength(0)
    expect(result.current.isPending).toBe(false)

    pending.close()
  })

  // Auto-title cache update — backend emits `event: title` on first user
  // turn after PATCHing the session.title. Frontend optimistically patches
  // the cache so the sidebar updates without a refetch round-trip.
  it('patches the chat-sessions cache when SSE emits a title for a placeholder session', async () => {
    const sseBody =
      'event: title\ndata: {"title":"New summary"}\n\n' +
      'event: done\ndata: {"message_id":"m1"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    queryClient.setQueryData(['chat-sessions'], {
      sessions: [{ id: 's1', title: 'New chat', message_count: 0 }],
      total: 1,
    })

    const { result } = renderHook(() => useChat({ sessionId: 's1' }), {
      wrapper: makeWrapperWithClient(queryClient),
    })

    await act(async () => {
      result.current.send('Tell me about widgets')
    })

    await waitFor(() => {
      const cached = queryClient.getQueryData<{
        sessions: Array<{ id: string; title: string }>
      }>(['chat-sessions'])
      expect(cached?.sessions[0]?.title).toBe('New summary')
    })
  })

  // Manual-rename guard: if the user has already renamed, the title SSE
  // event must NOT clobber their choice.
  it('does not overwrite a user-renamed title when SSE emits a title', async () => {
    const sseBody =
      'event: title\ndata: {"title":"New summary"}\n\n' +
      'event: done\ndata: {"message_id":"m2"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    queryClient.setQueryData(['chat-sessions'], {
      sessions: [{ id: 's1', title: 'My custom name', message_count: 0 }],
      total: 1,
    })

    const { result } = renderHook(() => useChat({ sessionId: 's1' }), {
      wrapper: makeWrapperWithClient(queryClient),
    })

    await act(async () => {
      result.current.send('Tell me about widgets')
    })

    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })

    const cached = queryClient.getQueryData<{
      sessions: Array<{ id: string; title: string }>
    }>(['chat-sessions'])
    expect(cached?.sessions[0]?.title).toBe('My custom name')
  })

  // U15 lazy creation: when `sessionId` is null and the user sends, the
  // hook targets the `'new'` sentinel; the backend creates the row
  // inline and emits `event: session_created` carrying the real UUID;
  // the hook patches `['chat-sessions']` with a stub row so the sidebar
  // updates immediately, and the URL swaps to `/chat/<id>`.
  it('passes "new" sentinel and patches chat-sessions cache on session_created (U15)', async () => {
    const sseBody =
      'event: session_created\ndata: {"session_id":"new-id-1","source_ids":[]}\n\n' +
      'event: title\ndata: {"title":"Lazy title"}\n\n' +
      'event: done\ndata: {"message_id":"m1"}\n\n'

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([sseBody]),
    })
    vi.stubGlobal('fetch', fetchMock)

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    const { result } = renderHook(() => useChat({ sessionId: null }), {
      wrapper: makeWrapperWithClient(queryClient),
    })

    await act(async () => {
      result.current.send('Hello world')
    })

    // The fetch URL must hit the sentinel path: the backend turns this
    // into a lazy-create.
    const lastCall = fetchMock.mock.calls[0]
    const url = lastCall?.[0] as string
    expect(url).toMatch(/\/api\/v1\/chat\/sessions\/new\/messages$/)

    // The cache is now seeded with the freshly-minted id; the title is
    // either still null (race: session_created arrived but title hadn't
    // landed yet) or 'Lazy title' (race: title landed before assertion).
    // Either is acceptable — the row's PRESENCE is the U15 contract.
    await waitFor(() => {
      const cached = queryClient.getQueryData<{
        sessions: Array<{ id: string; title: string | null }>
      }>(['chat-sessions'])
      expect(cached?.sessions.some((s) => s.id === 'new-id-1')).toBe(true)
    })

    // Eventual title patch — `event: title` fires AFTER `session_created`
    // in the stream, so we wait for the seeded row's title to flip from
    // null to the AI-minted string.
    await waitFor(() => {
      const cached = queryClient.getQueryData<{
        sessions: Array<{ id: string; title: string | null }>
      }>(['chat-sessions'])
      const row = cached?.sessions.find((s) => s.id === 'new-id-1')
      expect(row?.title).toBe('Lazy title')
    })
  })
})
