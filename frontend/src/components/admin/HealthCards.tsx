'use client'

import { apiClient } from '@/lib/api-client'
import type { HealthCheck, SystemHealth } from '@/types/admin-analytics'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  CpuIcon,
  DatabaseIcon,
  HardDriveIcon,
  XCircleIcon,
  ZapIcon,
} from 'lucide-react'
import type { ComponentType } from 'react'

type Service = HealthCheck['service']
type Status = HealthCheck['status']
type IconComponent = ComponentType<{ className?: string }>

const SERVICE_ICON: Record<Service, IconComponent> = {
  database: DatabaseIcon,
  redis: ZapIcon,
  minio: HardDriveIcon,
  celery: CpuIcon,
}

const STATUS_STYLES: Record<Status, { icon: IconComponent; color: string }> = {
  ok: { icon: CheckCircleIcon, color: 'text-green-600' },
  degraded: { icon: AlertTriangleIcon, color: 'text-amber-500' },
  down: { icon: XCircleIcon, color: 'text-red-600' },
}

export function HealthCards() {
  const { data } = useQuery<SystemHealth>({
    queryKey: ['health', 'detail'],
    queryFn: () => apiClient.get<SystemHealth>('/health/detail').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  const checks = data?.checks ?? []

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {checks.map((check) => {
        const ServiceIcon = SERVICE_ICON[check.service]
        const { icon: StatusIcon, color } = STATUS_STYLES[check.status]

        return (
          <div
            key={check.service}
            role="status"
            aria-label={`${check.service} is ${check.status}`}
            className="flex flex-col gap-2 rounded-lg border bg-card p-4"
          >
            <div className="flex items-center justify-between">
              <ServiceIcon className="h-5 w-5 text-muted-foreground" />
              <StatusIcon className={`h-4 w-4 ${color}`} />
            </div>
            <p className="font-medium capitalize">{check.service}</p>
            <p className={`text-sm ${color}`}>{check.status}</p>
            {check.latency_ms !== null && (
              <p className="text-xs text-muted-foreground">{check.latency_ms} ms</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
