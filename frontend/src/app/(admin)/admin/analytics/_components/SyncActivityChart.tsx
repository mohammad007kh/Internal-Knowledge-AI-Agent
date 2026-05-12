'use client'

import { Skeleton } from '@/components/ui/skeleton'
import type { SyncActivityPoint } from '@/lib/api/analytics'
import { ChartCard } from './ChartCard'
import { type BarsWithOverlayBar, shortDay, useBarsWithOverlay } from './chartHooks'

// indigo-500 (success) / red-500 (failed); overlay = sky-500 (docs + chunks).
const BAR_COLORS = ['#6366f1', '#ef4444'] as const
const OVERLAY_COLOR = '#0ea5e9'

export interface SyncActivityChartProps {
  data: SyncActivityPoint[] | undefined
  loading: boolean
}

export function SyncActivityChart({ data, loading }: SyncActivityChartProps) {
  const points: SyncActivityPoint[] = data ?? []
  const totalDocs = points.reduce((s, p) => s + p.documents, 0)
  const totalChunks = points.reduce((s, p) => s + p.chunks, 0)

  const bars: BarsWithOverlayBar[] = points.map((p) => ({
    label: shortDay(p.date),
    segments: [p.success, p.failed],
    overlay: p.documents + p.chunks,
  }))
  const canvasRef = useBarsWithOverlay(bars, BAR_COLORS, OVERLAY_COLOR)

  return (
    <ChartCard
      title="Sync activity"
      subtitle="jobs per day · line = documents + chunks (right axis)"
      actions={
        <span className="text-xs text-muted-foreground tabular-nums">
          {totalDocs.toLocaleString()} docs · {totalChunks.toLocaleString()} chunks
        </span>
      }
    >
      {loading ? (
        <Skeleton className="h-[200px] w-full" />
      ) : points.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No sync runs in this period.</p>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            width={520}
            height={200}
            role="img"
            aria-label="Bar chart: daily sync jobs with a documents/chunks overlay line"
            className="w-full"
          />
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <Swatch color="#6366f1" label="Success" />
            <Swatch color="#ef4444" label="Failed" />
            <Swatch color={OVERLAY_COLOR} label="Docs + chunks" />
          </ul>
        </>
      )}
    </ChartCard>
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
