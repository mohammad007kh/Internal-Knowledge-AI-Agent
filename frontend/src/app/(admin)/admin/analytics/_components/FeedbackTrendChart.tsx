'use client'

import { Skeleton } from '@/components/ui/skeleton'
import type { FeedbackTrendPoint } from '@/lib/api/analytics'
import { ChartCard } from './ChartCard'
import { type StackedBar, shortDay, useStackedBarChart } from './chartHooks'

// emerald-500 / red-500 / muted — stacked bottom → top: up, down, no-rating.
const SEGMENT_COLORS = ['#10b981', '#ef4444', '#d1d5db'] as const

export interface FeedbackTrendChartProps {
  data: FeedbackTrendPoint[] | undefined
  loading: boolean
}

export function FeedbackTrendChart({ data, loading }: FeedbackTrendChartProps) {
  const points: FeedbackTrendPoint[] = data ?? []

  let up = 0
  let rated = 0
  for (const p of points) {
    up += p.up
    rated += p.up + p.down
  }
  const rollingRate = rated > 0 ? Math.round((up / rated) * 100) : null

  const bars: StackedBar[] = points.map((p) => ({
    label: shortDay(p.date),
    segments: [p.up, p.down, Math.max(0, p.answered - p.up - p.down)],
  }))
  const canvasRef = useStackedBarChart(bars, SEGMENT_COLORS)

  return (
    <ChartCard
      title="Answer feedback"
      subtitle="thumbs-up / thumbs-down / no rating, per day"
      actions={
        <span className="text-lg font-semibold tabular-nums">
          {rollingRate === null ? '—' : `${rollingRate}%`}
        </span>
      }
    >
      {loading ? (
        <Skeleton className="h-[200px] w-full" />
      ) : points.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No assistant answers in this period.</p>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            width={520}
            height={200}
            role="img"
            aria-label="Stacked bar chart: daily answer feedback"
            className="w-full"
          />
          <Legend />
        </>
      )}
    </ChartCard>
  )
}

function Legend() {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <Swatch color="#10b981" label="Thumbs up" />
      <Swatch color="#ef4444" label="Thumbs down" />
      <Swatch color="#d1d5db" label="No rating" />
    </ul>
  )
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <li className="inline-flex items-center gap-1.5">
      <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      {label}
    </li>
  )
}
