'use client'

import { createContext, useCallback, useContext, useMemo, useState } from 'react'

interface SelectedSessionContextValue {
  sessionId: string | null
  setSessionId: (id: string | null) => void
}

const SelectedSessionContext = createContext<SelectedSessionContextValue>({
  sessionId: null,
  setSessionId: () => {},
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
  const value = useMemo(() => ({ sessionId, setSessionId }), [sessionId, setSessionId])
  return <SelectedSessionContext.Provider value={value}>{children}</SelectedSessionContext.Provider>
}

export function useSelectedSession() {
  return useContext(SelectedSessionContext)
}
