'use client'

import { useSidebarState } from '@/hooks/use-sidebar-state'
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

export interface SidebarContextValue {
  /** Desktop collapsed flag (persisted across reloads via localStorage). */
  collapsed: boolean
  /** Toggle the desktop collapsed flag. */
  toggle: () => void
  /** Explicitly set the desktop collapsed flag. */
  setCollapsed: (next: boolean) => void
  /** True when the viewport is below the desktop breakpoint. */
  isMobile: boolean
  /** Whether the mobile sheet is open. */
  mobileOpen: boolean
  /** Open / close the mobile sheet. */
  setMobileOpen: (next: boolean) => void
}

const SidebarContext = createContext<SidebarContextValue | null>(null)

const MOBILE_BREAKPOINT = 768 // matches Tailwind `md`

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const handler = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(event.matches)
    }
    handler(mql)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return isMobile
}

interface SidebarProviderProps {
  children: ReactNode
}

export function SidebarProvider({ children }: SidebarProviderProps) {
  const { collapsed, setCollapsed, toggle } = useSidebarState()
  const isMobile = useIsMobile()
  const [mobileOpen, setMobileOpen] = useState(false)

  // Bind Ctrl/Cmd+B to toggle collapse on desktop only.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const isModifier = event.metaKey || event.ctrlKey
      if (!isModifier) return
      if (event.key !== 'b' && event.key !== 'B') return

      // Ignore when typing into an editable surface.
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      const isEditable =
        target?.isContentEditable || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (isEditable) return

      if (isMobile) return

      event.preventDefault()
      toggle()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isMobile, toggle])

  const handleSetMobileOpen = useCallback((next: boolean) => {
    setMobileOpen(next)
  }, [])

  const value = useMemo<SidebarContextValue>(
    () => ({
      collapsed,
      toggle,
      setCollapsed,
      isMobile,
      mobileOpen,
      setMobileOpen: handleSetMobileOpen,
    }),
    [collapsed, toggle, setCollapsed, isMobile, mobileOpen, handleSetMobileOpen]
  )

  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>
}

export function useSidebar(): SidebarContextValue {
  const ctx = useContext(SidebarContext)
  if (!ctx) {
    throw new Error('useSidebar must be used within a <SidebarProvider>')
  }
  return ctx
}
