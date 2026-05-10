'use client'

import type { ListAuditLogParams } from '@/lib/api/audit-log'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Filter state for the /admin/audit-log toolbar.
 *
 * Kept flat + serializable so it round-trips through URL params cleanly.
 * Empty strings represent "no filter" — we never put empty values on the
 * wire or in the URL.
 *
 * `from` / `to` are ISO 8601 strings *or* date-only `YYYY-MM-DD` (the
 * date pickers emit the latter; the backend's Pydantic datetime parser
 * handles both).  We do NOT normalise to a fixed offset here — that
 * would make the URL ambiguous about whether the admin meant "midnight
 * local" or "midnight UTC".  Callers serialise the `Date` selected in
 * the picker as the URL-friendly date-only string.
 */
export interface AuditLogFilterState {
  search: string
  action: string
  resourceType: string
  adminUserId: string
  from: string
  to: string
  page: number
  pageSize: number
}

/** One active filter chip, rendered in the strip below the toolbar. */
export interface ActiveChip {
  id: string
  label: string
  remove: () => void
}

export interface UseAuditLogFiltersResult {
  state: AuditLogFilterState
  setState: (
    updater: (prev: AuditLogFilterState) => AuditLogFilterState
  ) => void
  setPage: (page: number) => void
  setPageSize: (pageSize: number) => void
  /** Filter set forwarded to the API client (omits empty values). */
  apiParams: ListAuditLogParams
  activeChips: readonly ActiveChip[]
  clearAll: () => void
  hasActiveFilters: boolean
}

const DEFAULT_PAGE_SIZE = 50

const DEFAULT_STATE: AuditLogFilterState = {
  search: '',
  action: '',
  resourceType: '',
  adminUserId: '',
  from: '',
  to: '',
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
}

const SEARCH_DEBOUNCE_MS = 250

// ---- URL serialization ------------------------------------------------------

// Sentinel used internally by the action / resource-type Selects (Radix
// disallows empty-string values).  If a sentinel ever reaches the URL —
// e.g. a user hand-types `?action=__all__` or pastes a stale link — we
// must NOT forward it to the API; treat it as "no filter".
const URL_SENTINELS = new Set<string>(['__all__'])

function readFilterParam(params: URLSearchParams, key: string): string {
  const raw = params.get(key)?.trim() ?? ''
  return URL_SENTINELS.has(raw) ? '' : raw
}

export function parseStateFromParams(params: URLSearchParams): AuditLogFilterState {
  const state: AuditLogFilterState = { ...DEFAULT_STATE }
  state.search = params.get('q')?.trim() ?? ''
  state.action = readFilterParam(params, 'action')
  state.resourceType = readFilterParam(params, 'resource_type')
  state.adminUserId = params.get('admin_user_id')?.trim() ?? ''
  state.from = params.get('from')?.trim() ?? ''
  state.to = params.get('to')?.trim() ?? ''
  const pageRaw = Number.parseInt(params.get('page') ?? '', 10)
  if (Number.isFinite(pageRaw) && pageRaw >= 1) {
    state.page = pageRaw
  }
  const sizeRaw = Number.parseInt(params.get('page_size') ?? '', 10)
  if (Number.isFinite(sizeRaw) && sizeRaw >= 1 && sizeRaw <= 200) {
    state.pageSize = sizeRaw
  }
  return state
}

export function serializeStateToParams(state: AuditLogFilterState): string {
  const params = new URLSearchParams()
  if (state.search.trim() !== '') params.set('q', state.search.trim())
  if (state.action !== '') params.set('action', state.action)
  if (state.resourceType !== '') params.set('resource_type', state.resourceType)
  if (state.adminUserId !== '') params.set('admin_user_id', state.adminUserId)
  if (state.from !== '') params.set('from', state.from)
  if (state.to !== '') params.set('to', state.to)
  if (state.page !== 1) params.set('page', String(state.page))
  if (state.pageSize !== DEFAULT_PAGE_SIZE) {
    params.set('page_size', String(state.pageSize))
  }
  return params.toString()
}

// ---- Filter -> API param projection ----------------------------------------

/**
 * Pure function: project the state shape onto the API client's params.
 * Empty strings become absent keys — never `''` on the wire.
 */
export function stateToApiParams(state: AuditLogFilterState): ListAuditLogParams {
  const out: ListAuditLogParams = {
    page: state.page,
    page_size: state.pageSize,
  }
  if (state.search.trim() !== '') out.search = state.search.trim()
  if (state.action !== '') out.action = state.action
  if (state.resourceType !== '') out.resource_type = state.resourceType
  if (state.adminUserId !== '') out.admin_user_id = state.adminUserId
  if (state.from !== '') out.from = state.from
  if (state.to !== '') out.to = state.to
  return out
}

// ---- Helpers ----------------------------------------------------------------

function statesEqual(a: AuditLogFilterState, b: AuditLogFilterState): boolean {
  return (
    a.search === b.search &&
    a.action === b.action &&
    a.resourceType === b.resourceType &&
    a.adminUserId === b.adminUserId &&
    a.from === b.from &&
    a.to === b.to &&
    a.page === b.page &&
    a.pageSize === b.pageSize
  )
}

// ---- Hook -------------------------------------------------------------------

/**
 * Owns filter + pagination state for /admin/audit-log, with URL sync.
 *
 *  - Reads URL params once on mount.
 *  - Writes URL via `router.replace` (no history spam) on changes.
 *  - Search input is debounced 250ms before being committed to URL/API.
 *  - Any filter mutation (other than `setPage`/`setPageSize`) resets `page`
 *    back to 1 — otherwise the user filters and lands on a stale empty page.
 */
export function useAuditLogFilters(): UseAuditLogFiltersResult {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Read initial state from URL exactly once.
  const initialStateRef = useRef<AuditLogFilterState | null>(null)
  if (initialStateRef.current === null) {
    initialStateRef.current = parseStateFromParams(
      searchParams ? new URLSearchParams(searchParams.toString()) : new URLSearchParams()
    )
  }

  const [state, setStateRaw] = useState<AuditLogFilterState>(initialStateRef.current)

  const setState = useCallback(
    (updater: (prev: AuditLogFilterState) => AuditLogFilterState) => {
      setStateRaw((prev) => {
        const next = updater(prev)
        return statesEqual(prev, next) ? prev : next
      })
    },
    []
  )

  const setPage = useCallback((page: number) => {
    setStateRaw((prev) => (prev.page === page ? prev : { ...prev, page }))
  }, [])

  const setPageSize = useCallback((pageSize: number) => {
    setStateRaw((prev) =>
      prev.pageSize === pageSize ? prev : { ...prev, pageSize, page: 1 }
    )
  }, [])

  // Debounce search before committing to URL — other filters apply
  // immediately. The debounced value is what we serialise into the URL
  // and into apiParams (so React Query keys don't churn on every keystroke).
  const [debouncedSearch, setDebouncedSearch] = useState(state.search)
  useEffect(() => {
    if (debouncedSearch === state.search) return
    const handle = setTimeout(() => setDebouncedSearch(state.search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [state.search, debouncedSearch])

  // Sync state -> URL.
  const isFirstUrlSync = useRef(true)
  const lastSerialized = useRef<string | null>(null)
  useEffect(() => {
    const stateForUrl: AuditLogFilterState = { ...state, search: debouncedSearch }
    const qs = serializeStateToParams(stateForUrl)

    if (isFirstUrlSync.current) {
      isFirstUrlSync.current = false
      lastSerialized.current = qs
      return
    }

    if (qs === lastSerialized.current) return
    lastSerialized.current = qs

    const target = qs ? `${pathname}?${qs}` : pathname
    router.replace(target, { scroll: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, debouncedSearch])

  const apiParams = useMemo<ListAuditLogParams>(
    () => stateToApiParams({ ...state, search: debouncedSearch }),
    [state, debouncedSearch]
  )

  const clearAll = useCallback(() => {
    setStateRaw(DEFAULT_STATE)
  }, [])

  const activeChips = useMemo<ActiveChip[]>(() => {
    const chips: ActiveChip[] = []
    if (state.search.trim() !== '') {
      chips.push({
        id: 'search',
        label: `Search: "${state.search.trim()}"`,
        remove: () => setStateRaw((prev) => ({ ...prev, search: '', page: 1 })),
      })
    }
    if (state.action !== '') {
      chips.push({
        id: 'action',
        label: `Action: ${state.action}`,
        remove: () => setStateRaw((prev) => ({ ...prev, action: '', page: 1 })),
      })
    }
    if (state.resourceType !== '') {
      chips.push({
        id: 'resource_type',
        label: `Resource: ${state.resourceType}`,
        remove: () => setStateRaw((prev) => ({ ...prev, resourceType: '', page: 1 })),
      })
    }
    if (state.adminUserId !== '') {
      chips.push({
        id: 'admin_user_id',
        label: `Admin: ${state.adminUserId.slice(0, 8)}…`,
        remove: () => setStateRaw((prev) => ({ ...prev, adminUserId: '', page: 1 })),
      })
    }
    if (state.from !== '') {
      chips.push({
        id: 'from',
        label: `From: ${state.from}`,
        remove: () => setStateRaw((prev) => ({ ...prev, from: '', page: 1 })),
      })
    }
    if (state.to !== '') {
      chips.push({
        id: 'to',
        label: `To: ${state.to}`,
        remove: () => setStateRaw((prev) => ({ ...prev, to: '', page: 1 })),
      })
    }
    return chips
  }, [state])

  const hasActiveFilters =
    state.search.trim() !== '' ||
    state.action !== '' ||
    state.resourceType !== '' ||
    state.adminUserId !== '' ||
    state.from !== '' ||
    state.to !== ''

  return {
    state,
    setState,
    setPage,
    setPageSize,
    apiParams,
    activeChips,
    clearAll,
    hasActiveFilters,
  }
}
