'use client'

import { useParams, useRouter } from 'next/navigation'
import { createContext, useCallback, useContext, useMemo, useRef } from 'react'

type AbortHandler = () => void

interface SetSessionOptions {
  /**
   * When `true`, navigate via `router.replace` instead of `router.push`.
   * Use for auto-created sessions where adding a history entry for the
   * intermediate `/chat` (empty) state would be noise on Back.
   */
  replace?: boolean
}

interface SelectedSessionContextValue {
  sessionId: string | null
  setSessionId: (id: string | null, options?: SetSessionOptions) => void
  /**
   * Register an abort handler that external callers (e.g. SessionList when
   * deleting the active session) can invoke via `abortStream()` to cancel an
   * in-flight chat stream before the selection changes. Returns an
   * unregister function.
   */
  registerAbortStream: (handler: AbortHandler) => () => void
  /** Invoke the currently registered abort handler, if any. */
  abortStream: () => void
}

const SelectedSessionContext = createContext<SelectedSessionContextValue>({
  sessionId: null,
  setSessionId: () => {},
  registerAbortStream: () => () => {},
  abortStream: () => {},
})

/**
 * Provides the currently-selected chat session, sourced from the URL.
 *
 * The canonical sessionId is the `[sessionId]` segment of `/chat/[sessionId]`
 * (read via `useParams`). On routes without that segment (e.g. `/chat`,
 * `/sources`, `/settings`) `sessionId` is `null`, which is the empty-state
 * landing for the chat surface.
 *
 * `setSessionId(id)` is a navigation: it `router.push`es to `/chat/<id>`
 * (or `/chat` when `id` is `null`). Browser back/forward therefore moves
 * between sessions, and refresh preserves the active chat.
 */
export function SelectedSessionProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const params = useParams<{ sessionId?: string }>()
  // useParams may return a string or string[] for catch-all routes; coerce
  // defensively. An empty string is treated as "no selection".
  const rawId = params?.sessionId
  const sessionId =
    typeof rawId === 'string' && rawId.length > 0
      ? rawId
      : Array.isArray(rawId) && rawId.length > 0
        ? rawId[0]
        : null

  const setSessionId = useCallback(
    (id: string | null, options?: SetSessionOptions) => {
      const target = id ? `/chat/${id}` : '/chat'
      if (options?.replace) {
        router.replace(target)
      } else {
        router.push(target)
      }
    },
    [router]
  )

  const abortHandlerRef = useRef<AbortHandler | null>(null)
  const registerAbortStream = useCallback((handler: AbortHandler) => {
    abortHandlerRef.current = handler
    return () => {
      if (abortHandlerRef.current === handler) {
        abortHandlerRef.current = null
      }
    }
  }, [])
  const abortStream = useCallback(() => {
    abortHandlerRef.current?.()
  }, [])

  const value = useMemo(
    () => ({ sessionId, setSessionId, registerAbortStream, abortStream }),
    [sessionId, setSessionId, registerAbortStream, abortStream]
  )
  return <SelectedSessionContext.Provider value={value}>{children}</SelectedSessionContext.Provider>
}

export function useSelectedSession() {
  return useContext(SelectedSessionContext)
}
