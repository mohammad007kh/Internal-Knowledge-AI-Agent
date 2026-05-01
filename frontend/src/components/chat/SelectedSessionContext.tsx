'use client'

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

type AbortHandler = () => void

interface SelectedSessionContextValue {
  sessionId: string | null
  setSessionId: (id: string | null) => void
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

export function SelectedSessionProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [sessionId, setSessionIdState] = useState<string | null>(null)
  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id)
  }, [])

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
