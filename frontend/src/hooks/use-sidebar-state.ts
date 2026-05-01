'use client'

import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'ui:sidebar-collapsed'

function readStoredCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function writeStoredCollapsed(value: boolean): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    // Ignore storage failures (private mode, quota, etc.)
  }
}

/**
 * SSR-safe hook that reads/writes the sidebar collapsed flag from localStorage.
 *
 * Returns `false` on the first render (server + initial client paint) and then
 * hydrates to the persisted value in a `useEffect` to avoid hydration mismatch.
 */
export function useSidebarState(): {
  collapsed: boolean
  setCollapsed: (next: boolean) => void
  toggle: () => void
} {
  const [collapsed, setCollapsedState] = useState<boolean>(false)

  // Hydrate persisted value after mount.
  useEffect(() => {
    setCollapsedState(readStoredCollapsed())
  }, [])

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next)
    writeStoredCollapsed(next)
  }, [])

  const toggle = useCallback(() => {
    setCollapsedState((prev) => {
      const next = !prev
      writeStoredCollapsed(next)
      return next
    })
  }, [])

  return { collapsed, setCollapsed, toggle }
}
