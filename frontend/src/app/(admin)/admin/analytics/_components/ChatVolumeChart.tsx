'use client'

import { Skeleton } from '@/components/ui/skeleton'
import type { ChatVolumePoint } from '@/lib/api/analytics'
import { ChartCard } from './ChartCard'
import { type AreaPoint, shortDay, useAreaChart } from './chartHooks'

export interface ChatVolumeChartProps {
  data: ChatVolumePoint[] | undefined
  loading: boolean
}

export function ChatVolumeChart({ data, loading }: ChatVolumeChartProps) {
  const points: ChatVolumePoint[] = data ?? []
  const total = points.reduce((sum, p) => sum + p.count, 0)
  const areaData: AreaPoint[] = points.map((p) => ({ label: shortDay(p.date), value: p.count }))
  const canvasRef = useAreaChart(areaData)

  return (
    <ChartCard
      title="Chat volume"
      actions={<span className="text-xs text-muted-foreground tabular-nums">{total.toLocaleString()} total</span>}
    >
      {loading ? (
        <Skeleton className="h-[200px] w-full" />
      ) : points.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No chat activity in this period.</p>
      ) : (
        <canvas
          ref={canvasRef}
          width={520}
          height={200}
          role="img"
          aria-label={`Area chart: chat volume, ${total} messages total`}
          className="w-full"
        />
      )}
    </ChartCard>
  )
}
