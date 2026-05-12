'use client'

import {
  type AnalyticsRange,
  getAnalyticsOverview,
  getChatVolume,
  getFeedbackTrend,
  getNeedsAttention,
  getSchemaStudies,
  getSourceHealth,
  getSyncActivity,
} from '@/lib/api/analytics'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

/**
 * React-query hooks for the `/admin/analytics` dashboard.
 *
 * Range-aware hooks use `placeholderData: keepPreviousData` so flipping the
 * 24h/7d/30d/90d toggle keeps the prior data on screen until the new payload
 * lands — no flicker, no layout jump.
 *
 * Snapshot hooks (source-health, schema-studies, needs-attention) are
 * point-in-time and take no range.
 */

const KEY = ['admin', 'analytics'] as const

const STALE_TIME_MS = 30_000

export function useAnalyticsOverview(range: AnalyticsRange) {
  return useQuery({
    queryKey: [...KEY, 'overview', range],
    queryFn: () => getAnalyticsOverview(range),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
  })
}

export function useChatVolume(range: AnalyticsRange) {
  return useQuery({
    queryKey: [...KEY, 'chat-volume', range],
    queryFn: () => getChatVolume(range),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
  })
}

export function useFeedbackTrend(range: AnalyticsRange) {
  return useQuery({
    queryKey: [...KEY, 'feedback-trend', range],
    queryFn: () => getFeedbackTrend(range),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
  })
}

export function useSyncActivity(range: AnalyticsRange) {
  return useQuery({
    queryKey: [...KEY, 'sync-activity', range],
    queryFn: () => getSyncActivity(range),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME_MS,
  })
}

export function useSourceHealth() {
  return useQuery({
    queryKey: [...KEY, 'source-health'],
    queryFn: getSourceHealth,
    staleTime: STALE_TIME_MS,
  })
}

export function useSchemaStudies() {
  return useQuery({
    queryKey: [...KEY, 'schema-studies'],
    queryFn: getSchemaStudies,
    staleTime: STALE_TIME_MS,
  })
}

export function useNeedsAttention() {
  return useQuery({
    queryKey: [...KEY, 'needs-attention'],
    queryFn: getNeedsAttention,
    staleTime: STALE_TIME_MS,
  })
}
