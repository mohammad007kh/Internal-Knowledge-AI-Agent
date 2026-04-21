'use client'

import { apiClient } from '@/lib/api-client'
import type { ActivityEvent } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangleIcon, InfoIcon, XCircleIcon } from 'lucide-react'
import type { ComponentType } from 'react'

type Severity = ActivityEvent['severity']
type IconComponent = ComponentType<{ className?: string }>

const SEV_STYLES: Record<Severity, { icon: IconComponent; color: string }> = {
  info: { icon: InfoIcon, color: 'text-blue-500' },
  warning: { icon: AlertTriangleIcon, color: 'text-amber-500' },
  error: { icon: XCircleIcon, color: 'text-red-600' },
}

export function ActivityFeed() {
  const { data } = useQuery<ActivityEvent[]>({
    queryKey: ['admin', 'analytics', 'activity'],
    queryFn: () =>
      apiClient.get<ActivityEvent[]>('/api/v1/admin/analytics/activity?limit=20').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  const events = data ?? []

  return (
    <div className="rounded-lg border bg-card p-4">
      <h2 className="mb-4 font-semibold">Recent Activity</h2>
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No recent activity.</p>
      ) : (
        <ol aria-live="polite" className="space-y-3">
          {events.map((ev) => {
            const { icon: Icon, color } = SEV_STYLES[ev.severity]
            return (
              <li key={ev.id} className="flex items-start gap-3">
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${color}`} />
                <div className="flex-1">
                  <p className="text-sm">{ev.message}</p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(ev.created_at).toLocaleString()}
                  </p>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
