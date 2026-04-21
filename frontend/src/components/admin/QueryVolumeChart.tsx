'use client'

import { useBarChart } from '@/hooks/useBarChart'
import { apiClient } from '@/lib/api-client'
import type { DailyQueryCount } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'

export function QueryVolumeChart() {
  const { data } = useQuery<DailyQueryCount[]>({
    queryKey: ['admin', 'analytics', 'queries'],
    queryFn: () =>
      apiClient.get<DailyQueryCount[]>('/api/v1/admin/analytics/queries?days=14').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  const counts = data ?? []
  const barData = counts.map((d) => ({ label: d.date, value: d.count }))
  const total = counts.reduce((sum, d) => sum + d.count, 0)

  const canvasRef = useBarChart(barData)

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold">Query Volume (14d)</h2>
        <span className="text-sm text-muted-foreground">{total.toLocaleString()} total</span>
      </div>
      <canvas
        ref={canvasRef}
        width={480}
        height={200}
        role="img"
        aria-label={`Bar chart: query volume over last 14 days, ${total} total`}
        className="w-full"
      />
    </div>
  )
}
