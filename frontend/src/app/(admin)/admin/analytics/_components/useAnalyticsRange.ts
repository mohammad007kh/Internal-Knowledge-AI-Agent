'use client'

import { type AnalyticsRange, isAnalyticsRange } from '@/lib/api/analytics'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * URL-synced `?range=` state for the analytics dashboard.
 *
 * Mirrors the `useStageFilters` / `useAuditLogFilters` pattern:
 *  - reads the URL param exactly once on mount;
 *  - writes via `router.replace` (no history spam) on subsequent changes;
 *  - skips the write on the very first render so we don't replace the URL
 *    just from mounting.
 *
 * Default: `7d`.
 */

const DEFAULT_RANGE: AnalyticsRange = '7d'

export const RANGE_PARAM = 'range'

export function parseRangeFromParams(params: URLSearchParams): AnalyticsRange {
  const raw = params.get(RANGE_PARAM)?.trim() ?? ''
  return isAnalyticsRange(raw) ? raw : DEFAULT_RANGE
}

export function serializeRangeToParams(range: AnalyticsRange): string {
  if (range === DEFAULT_RANGE) return ''
  const params = new URLSearchParams()
  params.set(RANGE_PARAM, range)
  return params.toString()
}

export interface UseAnalyticsRangeResult {
  range: AnalyticsRange
  setRange: (range: AnalyticsRange) => void
}

export function useAnalyticsRange(): UseAnalyticsRangeResult {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Read the initial range from the URL exactly once.
  const initialRef = useRef<AnalyticsRange | null>(null)
  if (initialRef.current === null) {
    initialRef.current = parseRangeFromParams(
      searchParams ? new URLSearchParams(searchParams.toString()) : new URLSearchParams()
    )
  }

  const [range, setRangeRaw] = useState<AnalyticsRange>(initialRef.current)

  const setRange = useCallback((next: AnalyticsRange) => {
    setRangeRaw((prev) => (prev === next ? prev : next))
  }, [])

  // Sync range -> URL.
  const isFirst = useRef(true)
  const lastSerialized = useRef<string | null>(null)
  useEffect(() => {
    const qs = serializeRangeToParams(range)
    if (isFirst.current) {
      isFirst.current = false
      lastSerialized.current = qs
      return
    }
    if (qs === lastSerialized.current) return
    lastSerialized.current = qs
    const target = qs ? `${pathname}?${qs}` : pathname
    router.replace(target, { scroll: false })
    // pathname is stable per page; router identity may churn — exclude both.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range])

  return { range, setRange }
}
