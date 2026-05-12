'use client'

import { Skeleton } from '@/components/ui/skeleton'
import type { SourceHealthBreakdown, StatusCount, TypeCount } from '@/lib/api/analytics'
import { ChartCard } from './ChartCard'

/**
 * SourceHealthPanel — labelled horizontal stacked bars (flex-div % widths,
 * like TopSourcesTable's progress bars; no donut primitive).
 *
 * Two bars:
 *   • by type        — web_url / database / confluence / …
 *   • by health      — connection_status for DB sources + status for the rest,
 *                      merged into one "health" bar so the admin sees the
 *                      healthy-vs-not split at a glance.
 */

const TYPE_COLORS: Record<string, string> = {
  web_url: '#6366f1',
  file_upload: '#0ea5e9',
  database: '#8b5cf6',
  confluence: '#f59e0b',
  sharepoint: '#10b981',
}
const TYPE_FALLBACK = '#9ca3af'

const HEALTH_COLORS: Record<string, string> = {
  healthy: '#10b981',
  active: '#10b981',
  ready: '#10b981',
  degraded: '#f59e0b',
  pending: '#f59e0b',
  unknown: '#9ca3af',
  failed: '#ef4444',
  error: '#ef4444',
}
const HEALTH_FALLBACK = '#9ca3af'

interface Segment {
  key: string
  count: number
  color: string
}

function buildSegments(
  rows: ReadonlyArray<{ key: string; count: number }>,
  colorOf: (key: string) => string
): Segment[] {
  return rows
    .filter((r) => r.count > 0)
    .map((r) => ({ key: r.key, count: r.count, color: colorOf(r.key) }))
    .sort((a, b) => b.count - a.count)
}

function StackedRow({ segments }: { segments: Segment[] }) {
  const total = segments.reduce((s, seg) => s + seg.count, 0)
  if (total === 0) {
    return <p className="text-xs text-muted-foreground">No data.</p>
  }
  return (
    <div className="space-y-2">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label="Distribution bar">
        {segments.map((seg) => (
          <div
            key={seg.key}
            className="h-3"
            style={{ width: `${(seg.count / total) * 100}%`, backgroundColor: seg.color }}
            title={`${seg.key}: ${seg.count}`}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {segments.map((seg) => (
          <li key={seg.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: seg.color }} />
            <span className="capitalize">{seg.key.replace(/_/g, ' ')}</span>
            <span className="tabular-nums">{seg.count}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export interface SourceHealthPanelProps {
  data: SourceHealthBreakdown | undefined
  loading: boolean
}

export function SourceHealthPanel({ data, loading }: SourceHealthPanelProps) {
  const typeRows = (data?.by_type ?? []).map((t: TypeCount) => ({ key: t.type, count: t.count }))
  // Merge DB connection-status + non-DB status into one "health" view, summing
  // duplicate keys (e.g. both lists may carry "active"/"healthy").
  const healthMap = new Map<string, number>()
  for (const r of (data?.by_connection_status ?? []) as StatusCount[]) {
    healthMap.set(r.status, (healthMap.get(r.status) ?? 0) + r.count)
  }
  for (const r of (data?.by_status ?? []) as StatusCount[]) {
    healthMap.set(r.status, (healthMap.get(r.status) ?? 0) + r.count)
  }
  const healthRows = Array.from(healthMap, ([key, count]) => ({ key, count }))

  const typeSegments = buildSegments(typeRows, (k) => TYPE_COLORS[k] ?? TYPE_FALLBACK)
  const healthSegments = buildSegments(healthRows, (k) => HEALTH_COLORS[k.toLowerCase()] ?? HEALTH_FALLBACK)

  return (
    <ChartCard title="Source health">
      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : typeSegments.length === 0 && healthSegments.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No sources configured yet.</p>
      ) : (
        <div className="space-y-5">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">By type</p>
            <StackedRow segments={typeSegments} />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">By health</p>
            <StackedRow segments={healthSegments} />
          </div>
        </div>
      )}
    </ChartCard>
  )
}
