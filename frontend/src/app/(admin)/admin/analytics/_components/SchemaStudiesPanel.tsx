'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { RecentSchemaFailure, SchemaStudiesBreakdown, StatusCount } from '@/lib/api/analytics'
import Link from 'next/link'
import { ChartCard } from './ChartCard'
import { timeAgo } from './timeAgo'

const STATUS_COLORS: Record<string, string> = {
  READY: '#10b981',
  READY_PARTIAL: '#34d399',
  STUDYING: '#0ea5e9',
  QUEUED: '#9ca3af',
  STALE: '#f59e0b',
  FAILED: '#ef4444',
}
const STATUS_FALLBACK = '#9ca3af'

function colorOf(status: string): string {
  if (STATUS_COLORS[status]) return STATUS_COLORS[status]
  if (status.toUpperCase().includes('FAILED')) return STATUS_COLORS.FAILED
  return STATUS_FALLBACK
}

function truncate(text: string | null | undefined, max = 80): string {
  if (!text) return '—'
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export interface SchemaStudiesPanelProps {
  data: SchemaStudiesBreakdown | undefined
  loading: boolean
}

export function SchemaStudiesPanel({ data, loading }: SchemaStudiesPanelProps) {
  const statusRows: StatusCount[] = (data?.by_schema_status ?? []).filter((r) => r.count > 0)
  const total = statusRows.reduce((s, r) => s + r.count, 0)
  const failures: RecentSchemaFailure[] = data?.recent_failures ?? []

  return (
    <ChartCard title="Schema studies">
      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : total === 0 && failures.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No database sources studied yet.</p>
      ) : (
        <div className="space-y-4">
          {total > 0 ? (
            <div className="space-y-2">
              <div
                className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label="Schema status distribution"
              >
                {statusRows.map((r) => (
                  <div
                    key={r.status}
                    className="h-3"
                    style={{ width: `${(r.count / total) * 100}%`, backgroundColor: colorOf(r.status) }}
                    title={`${r.status}: ${r.count}`}
                  />
                ))}
              </div>
              <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                {statusRows.map((r) => (
                  <li key={r.status} className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="inline-block h-2.5 w-2.5 rounded-sm"
                      style={{ backgroundColor: colorOf(r.status) }}
                    />
                    <span>{r.status}</span>
                    <span className="tabular-nums">{r.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Recent failed studies
            </p>
            {failures.length === 0 ? (
              <p className="text-xs text-muted-foreground">None — all studies succeeded.</p>
            ) : (
              <ul className="divide-y rounded-md border">
                {failures.map((f) => (
                  <li key={f.source_id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <Link
                      href={`/admin/sources/${f.source_id}`}
                      className="min-w-0 flex-1 truncate font-medium hover:underline"
                      title={f.source_name}
                    >
                      {f.source_name}
                    </Link>
                    {f.last_error_phase ? (
                      <Badge variant="destructive" className="shrink-0 text-[10px]">
                        {f.last_error_phase}
                      </Badge>
                    ) : null}
                    <span className="hidden min-w-0 flex-1 truncate text-muted-foreground sm:block" title={f.last_error_message ?? undefined}>
                      {truncate(f.last_error_message)}
                    </span>
                    <span className="shrink-0 text-muted-foreground tabular-nums">{timeAgo(f.finished_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </ChartCard>
  )
}
