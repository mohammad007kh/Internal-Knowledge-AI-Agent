'use client'

import { KpiTile } from '@/components/admin/KpiTile'
import { Sparkline } from '@/components/admin/Sparkline'
import type { AnalyticsOverview, ChatVolumePoint } from '@/lib/api/analytics'
import {
  ActivityIcon,
  DatabaseIcon,
  MessageSquareIcon,
  RefreshCwIcon,
  ShieldIcon,
  ThumbsUpIcon,
} from 'lucide-react'
import Link from 'next/link'

/**
 * KpiRow — the six hero KPIs across the top of /admin/analytics.
 *
 * 1. Chat messages (range window)  — count + Δ% vs prior window, 14-pt
 *    sparkline from chat-volume.
 * 2. Answer feedback score         — 👍 rate, "N rated / M answers" sub.
 * 3. Active sources                — red "X failed" sub when >0.
 * 4. Sync success rate (range)     — "N of M jobs".
 * 5. Schema studies                — "N ready · M failed", links into
 *    /admin/sources?schema_status=...
 * 6. Privileged actions today      — count.
 *
 * The period-delta KPIs (1, 4) react to the range; the rest are point-in-time
 * but live in the same `overview` payload so they refresh together.
 */

const SPARKLINE_POINTS = 14

export interface KpiRowProps {
  overview: AnalyticsOverview | undefined
  chatVolume: ChatVolumePoint[] | undefined
  loading: boolean
  /** The active range token — used only for the "Chat messages (Nd)" label. */
  rangeLabel: string
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value * 100)}%`
}

function deltaSub(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return 'no prior data'
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta}% vs prior period`
}

export function KpiRow({ overview, chatVolume, loading, rangeLabel }: KpiRowProps) {
  const gridClass = 'grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6'

  if (loading || !overview) {
    return (
      <div className={gridClass}>
        <KpiTile label={`Chat messages (${rangeLabel})`} value={null} loading />
        <KpiTile label="Answer feedback" value={null} loading />
        <KpiTile label="Active sources" value={null} loading />
        <KpiTile label={`Sync success (${rangeLabel})`} value={null} loading />
        <KpiTile label="Schema studies" value={null} loading />
        <KpiTile label="Privileged actions" value={null} loading />
      </div>
    )
  }

  const cm = overview.chat_messages
  const fb = overview.feedback
  const src = overview.sources
  const syn = overview.sync
  const studies = overview.schema_studies

  const sparkSeries = (chatVolume ?? [])
    .slice(-SPARKLINE_POINTS)
    .map((p) => (Number.isFinite(p.count) ? p.count : 0))

  return (
    <div className={gridClass}>
      <KpiTile
        label={`Chat messages (${rangeLabel})`}
        value={cm.count.toLocaleString()}
        sub={deltaSub(cm.delta_pct)}
        icon={<MessageSquareIcon className="h-4 w-4" aria-hidden />}
        sparkline={sparkSeries.length > 0 ? <Sparkline data={sparkSeries} ariaLabel="Chat volume" /> : undefined}
      />

      <KpiTile
        label="Answer feedback"
        value={pct(fb.up_rate)}
        sub={`${fb.rated.toLocaleString()} rated / ${fb.answered.toLocaleString()} answers`}
        icon={<ThumbsUpIcon className="h-4 w-4" aria-hidden />}
      />

      <KpiTile
        label="Active sources"
        value={src.active.toLocaleString()}
        sub={src.failed_connections > 0 ? `${src.failed_connections} failed` : 'all reachable'}
        icon={<DatabaseIcon className="h-4 w-4" aria-hidden />}
        className={src.failed_connections > 0 ? 'border-destructive/40' : undefined}
      />

      <KpiTile
        label={`Sync success (${rangeLabel})`}
        value={pct(syn.success_rate)}
        sub={`${syn.success.toLocaleString()} of ${syn.total.toLocaleString()} jobs`}
        icon={<RefreshCwIcon className="h-4 w-4" aria-hidden />}
      />

      <SchemaStudiesTile ready={studies.ready} failed={studies.failed} />

      <KpiTile
        label="Privileged actions"
        value={overview.privileged_actions_today.toLocaleString()}
        sub="today (UTC)"
        icon={<ShieldIcon className="h-4 w-4" aria-hidden />}
      />
    </div>
  )
}

function SchemaStudiesTile({ ready, failed }: { ready: number; failed: number }) {
  const value = `${ready} ready`
  const sub = failed > 0 ? `${failed} failed` : 'none failed'
  // The KpiTile is presentational; wrap a relative-positioned overlay link so
  // clicking the card jumps to the sources list. FX41 — the previous
  // ?schema_status=FAILED|READY filter was never honoured (the backend
  // GET /sources accepts no schema_status query, and the page never read it).
  // Drop the bogus query until a real filter is wired end-to-end.
  const href = '/admin/sources'
  return (
    <div className="relative">
      <KpiTile
        label="Schema studies"
        value={value}
        sub={sub}
        icon={<ActivityIcon className="h-4 w-4" aria-hidden />}
        className={failed > 0 ? 'border-destructive/40' : undefined}
      />
      <Link
        href={href}
        aria-label="View schema studies in sources"
        className="absolute inset-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </div>
  )
}
