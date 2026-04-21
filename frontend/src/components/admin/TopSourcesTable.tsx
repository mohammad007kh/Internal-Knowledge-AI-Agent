'use client'

import { apiClient } from '@/lib/api-client'
import type { SourceQueryStat } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'

export function TopSourcesTable() {
  const { data } = useQuery<SourceQueryStat[]>({
    queryKey: ['admin', 'analytics', 'top-sources'],
    queryFn: () =>
      apiClient.get<SourceQueryStat[]>('/api/v1/admin/analytics/top-sources?limit=10').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  const sources = data ?? []
  const maxCount = sources.reduce((max, s) => Math.max(max, s.query_count), 1)

  return (
    <div className="rounded-lg border bg-card p-4">
      <h2 className="mb-4 font-semibold">Top Sources</h2>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground">No query data yet.</p>
      ) : (
        <ol className="space-y-3">
          {sources.map((s, i) => (
            <li key={s.source_id} className="flex items-center gap-3">
              <span className="w-5 text-right text-sm text-muted-foreground">{i + 1}</span>
              <div className="flex-1">
                <p className="text-sm font-medium">{s.source_name}</p>
                <div className="mt-1 h-1.5 w-full rounded-full bg-muted">
                  <div
                    className="h-1.5 rounded-full bg-primary"
                    style={{ width: `${(s.query_count / maxCount) * 100}%` }}
                  />
                </div>
              </div>
              <span className="text-sm text-muted-foreground">{s.query_count}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
