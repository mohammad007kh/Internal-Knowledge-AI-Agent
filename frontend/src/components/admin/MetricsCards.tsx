'use client'

import { KpiTile } from '@/components/admin/KpiTile'
import { Sparkline } from '@/components/admin/Sparkline'
import { apiClient } from '@/lib/api-client'
import type { DailyQueryCount, SystemMetrics } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'
import { ClockIcon, DatabaseIcon, MessageSquareIcon, UsersIcon } from 'lucide-react'

const METRICS_REFETCH_INTERVAL_MS = 30_000
const METRICS_STALE_TIME_MS = 10_000
const QUERIES_DAYS = 14

export function MetricsCards() {
  const metricsQuery = useQuery<SystemMetrics>({
    queryKey: ['admin', 'analytics', 'metrics'],
    queryFn: () =>
      apiClient.get<SystemMetrics>('/api/v1/admin/analytics/metrics').then((r) => r.data),
    refetchInterval: METRICS_REFETCH_INTERVAL_MS,
    staleTime: METRICS_STALE_TIME_MS,
  })

  const queriesSeriesQuery = useQuery<DailyQueryCount[]>({
    queryKey: ['admin', 'analytics', 'queries', { days: QUERIES_DAYS }],
    queryFn: () =>
      apiClient
        .get<DailyQueryCount[]>(`/api/v1/admin/analytics/queries?days=${QUERIES_DAYS}`)
        .then((r) => r.data),
    refetchInterval: METRICS_REFETCH_INTERVAL_MS,
    staleTime: METRICS_STALE_TIME_MS,
  })

  if (metricsQuery.isError) {
    return null
  }

  const gridClassName = 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4'

  if (metricsQuery.isLoading || !metricsQuery.data) {
    return (
      <div className={gridClassName}>
        <KpiTile label="Active Users (7d)" value={null} loading />
        <KpiTile label="Active Sources" value={null} loading />
        <KpiTile label="Queries (7d)" value={null} loading />
        <KpiTile label="Avg Response" value={null} loading />
      </div>
    )
  }

  const metrics = metricsQuery.data
  const queriesSeries = queriesSeriesQuery.data
  const queriesSeriesAvailable =
    !queriesSeriesQuery.isLoading && !queriesSeriesQuery.isError && Array.isArray(queriesSeries)

  const sparkline = queriesSeriesAvailable ? (
    <Sparkline
      data={queriesSeries.map((q) =>
        typeof q.count === 'number' && Number.isFinite(q.count) ? q.count : 0
      )}
      ariaLabel="Queries last 14 days"
    />
  ) : undefined

  return (
    <div className={gridClassName}>
      <KpiTile
        label="Active Users (7d)"
        value={String(metrics.active_users_7d)}
        sub={`${metrics.total_users} total`}
        icon={<UsersIcon className="h-4 w-4" aria-hidden />}
      />
      <KpiTile
        label="Active Sources"
        value={String(metrics.active_sources)}
        icon={<DatabaseIcon className="h-4 w-4" aria-hidden />}
      />
      <KpiTile
        label="Queries (7d)"
        value={metrics.queries_7d.toLocaleString()}
        sub="Last 14 days"
        icon={<MessageSquareIcon className="h-4 w-4" aria-hidden />}
        sparkline={sparkline}
      />
      <KpiTile
        label="Avg Response"
        value={`${Math.round(metrics.avg_response_time_ms ?? 0)} ms`}
        icon={<ClockIcon className="h-4 w-4" aria-hidden />}
      />
    </div>
  )
}
