'use client'

import { KpiTile } from '@/components/admin/KpiTile'
import { Sparkline } from '@/components/admin/Sparkline'
import { coerceCount, formatRelative } from '@/features/sources/format'
import type { SourceListItem } from '@/lib/api/sources'
import { CheckCircle2Icon, ClockIcon, DatabaseIcon, FilesIcon } from 'lucide-react'

const GRID_CLASSNAME = 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4'

interface SourcesKpiStripProps {
  sources: readonly SourceListItem[]
  loading?: boolean
}

interface DerivedKpis {
  total: number
  active: number
  disabled: number
  documents: number
  perSourceDocs: number[]
  latestSyncAt: string | null
  latestSyncName: string | null
}

function deriveKpis(sources: readonly SourceListItem[]): DerivedKpis {
  let active = 0
  let disabled = 0
  let documents = 0
  let latestSyncAt: string | null = null
  let latestSyncName: string | null = null
  let latestSyncMs = Number.NEGATIVE_INFINITY

  const perSourceDocs: number[] = []

  for (const source of sources) {
    if (source.is_active) {
      active += 1
    } else {
      disabled += 1
    }

    const docs = coerceCount(source.latest_job?.documents_indexed)
    if (docs !== null) {
      documents += docs
      perSourceDocs.push(docs)
    } else {
      perSourceDocs.push(0)
    }

    const syncedAt = source.last_synced_at ?? source.latest_job?.completed_at ?? null
    if (syncedAt) {
      const ms = new Date(syncedAt).getTime()
      if (Number.isFinite(ms) && ms > latestSyncMs) {
        latestSyncMs = ms
        latestSyncAt = syncedAt
        latestSyncName = source.name
      }
    }
  }

  return {
    total: sources.length,
    active,
    disabled,
    documents,
    perSourceDocs,
    latestSyncAt,
    latestSyncName,
  }
}

export function SourcesKpiStrip({ sources, loading = false }: SourcesKpiStripProps) {
  if (loading) {
    return (
      <div className={GRID_CLASSNAME}>
        <KpiTile label="Total sources" value={null} loading />
        <KpiTile label="Active" value={null} loading />
        <KpiTile label="Documents indexed" value={null} loading />
        <KpiTile label="Last sync" value={null} loading />
      </div>
    )
  }

  const kpis = deriveKpis(sources)

  const sparkline =
    kpis.perSourceDocs.length > 1 ? (
      <Sparkline data={kpis.perSourceDocs} ariaLabel="Documents per source" />
    ) : undefined

  const lastSyncValue = kpis.latestSyncAt ? formatRelative(kpis.latestSyncAt) : '—'
  const lastSyncSub = kpis.latestSyncName ?? 'No syncs yet'

  return (
    <div className={GRID_CLASSNAME}>
      <KpiTile
        label="Total sources"
        value={kpis.total.toLocaleString()}
        sub={kpis.total === 1 ? 'configured' : 'configured'}
        icon={<DatabaseIcon className="h-4 w-4" aria-hidden />}
      />
      <KpiTile
        label="Active"
        value={kpis.active.toLocaleString()}
        sub={kpis.disabled > 0 ? `${kpis.disabled} disabled` : 'All enabled'}
        icon={<CheckCircle2Icon className="h-4 w-4" aria-hidden />}
      />
      <KpiTile
        label="Documents indexed"
        value={kpis.documents.toLocaleString()}
        sub="Per source trend"
        icon={<FilesIcon className="h-4 w-4" aria-hidden />}
        sparkline={sparkline}
      />
      <KpiTile
        label="Last sync"
        value={lastSyncValue}
        sub={lastSyncSub}
        icon={<ClockIcon className="h-4 w-4" aria-hidden />}
      />
    </div>
  )
}
