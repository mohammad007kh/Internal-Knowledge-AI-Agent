'use client'

import { apiClient } from '@/lib/api-client'
import type { SystemMetrics } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'
import { ClockIcon, DatabaseIcon, FileTextIcon, MessageSquareIcon, UsersIcon } from 'lucide-react'
import type { ComponentType } from 'react'

type IconComponent = ComponentType<{ className?: string }>

interface MetricCard {
  label: string
  value: string
  sub?: string
  icon: IconComponent
}

function buildCards(metrics: SystemMetrics): MetricCard[] {
  return [
    {
      label: 'Total Users',
      value: String(metrics.total_users),
      sub: `${metrics.active_users_7d} active (7d)`,
      icon: UsersIcon,
    },
    {
      label: 'Active Sources',
      value: String(metrics.active_sources),
      icon: DatabaseIcon,
    },
    {
      label: 'Documents Indexed',
      value: metrics.total_documents.toLocaleString(),
      icon: FileTextIcon,
    },
    {
      label: 'Queries (7d)',
      value: metrics.queries_7d.toLocaleString(),
      icon: MessageSquareIcon,
    },
    {
      label: 'Avg Response',
      value: `${Math.round(metrics.avg_response_time_ms)} ms`,
      icon: ClockIcon,
    },
  ]
}

export function MetricsCards() {
  const { data } = useQuery<SystemMetrics>({
    queryKey: ['admin', 'analytics', 'metrics'],
    queryFn: () => apiClient.get<SystemMetrics>('/admin/analytics/metrics').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  const cards = data ? buildCards(data) : []

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <div key={card.label} className="flex flex-col gap-2 rounded-lg border bg-card p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">{card.label}</p>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-2xl font-semibold">{card.value}</p>
            {card.sub && <p className="text-xs text-muted-foreground">{card.sub}</p>}
          </div>
        )
      })}
    </div>
  )
}
