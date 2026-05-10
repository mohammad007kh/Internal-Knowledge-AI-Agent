'use client'

/**
 * R6 — Source detail Overview tab, type-aware.
 *
 * The legacy Overview rendered three identical stat cards
 * (Documents / Chunks / Last synced) for every source type. An admin
 * walking into a Postgres database source needs different signal than one
 * walking into a 200-PDF Confluence dump, so the redesign:
 *
 *   1. Surfaces failure / partial / stale state above the fold so the
 *      most actionable message dominates.
 *   2. Replaces the generic stat row with three source-type-aware cards
 *      (Status / Coverage / Freshness).
 *   3. Renders one big "what is this source" card whose contents adapt
 *      to source_type — connection block + studying-agent state for DB,
 *      file count + breakdown for files, crawl details for web, OAuth +
 *      page count for connectors.
 */

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { SourceDetail } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import {
  AlertTriangleIcon,
  CircleAlertIcon,
  DatabaseIcon,
  FileTextIcon,
  GlobeIcon,
  LockIcon,
  PlugIcon,
} from 'lucide-react'

const DB_TYPES: ReadonlySet<string> = new Set([
  'postgresql',
  'mysql',
  'mssql',
  'mongodb',
])
const FILE_TYPES: ReadonlySet<string> = new Set([
  'pdf',
  'docx',
  'xlsx',
  'csv',
  'txt',
  'markdown',
  'file_upload',
])
const CONNECTOR_TYPES: ReadonlySet<string> = new Set([
  'confluence',
  'sharepoint',
  'notion',
  'google_drive',
])

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

// ---------------------------------------------------------------------------
// Failure / partial / stale callouts
// ---------------------------------------------------------------------------

interface OverviewCalloutsProps {
  source: SourceDetail
  isDbSource: boolean
  onRetrySync: () => void
}

export function OverviewCallouts({ source, isDbSource, onRetrySync }: OverviewCalloutsProps) {
  const latestJob = source.latest_job
  const jobFailed = latestJob?.status === 'failed'
  const studyPartial = source.study_state === 'READY_PARTIAL'
  const schemaStale = isDbSource && source.schema_status === 'STALE'
  if (!jobFailed && !studyPartial && !schemaStale) return null

  return (
    <div className="space-y-2">
      {jobFailed && (
        <Callout
          tone="destructive"
          icon={<CircleAlertIcon className="h-4 w-4" />}
          title="Last sync failed"
          body={latestJob?.error_message ?? 'See sync history for details.'}
          action={{ label: 'Retry', onClick: onRetrySync }}
        />
      )}
      {studyPartial && (
        <Callout
          tone="amber"
          icon={<AlertTriangleIcon className="h-4 w-4" />}
          title="Schema documented partially"
          body={
            source.last_error_phase
              ? `The studying agent's ${source.last_error_phase} phase didn't complete. Some tables may have shallow descriptions.`
              : 'At least one table failed AI description. Re-study to fill the gaps.'
          }
        />
      )}
      {schemaStale && (
        <Callout
          tone="amber"
          icon={<AlertTriangleIcon className="h-4 w-4" />}
          title="Schema may be stale"
          body="Drift detected since the last study. Re-study to refresh the documentation."
        />
      )}
    </div>
  )
}

interface CalloutProps {
  tone: 'destructive' | 'amber'
  icon: React.ReactNode
  title: string
  body: string
  action?: { label: string; onClick: () => void }
}

function Callout({ tone, icon, title, body, action }: CalloutProps) {
  const palette =
    tone === 'destructive'
      ? 'border-destructive/40 bg-destructive/5 text-destructive'
      : 'border-amber-500/40 bg-amber-500/5 text-amber-900 dark:text-amber-200'
  return (
    <div className={cn('flex items-start gap-3 rounded-md border p-3 text-sm', palette)}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        <p className="text-xs opacity-90">{body}</p>
      </div>
      {action ? (
        <Button size="sm" variant="outline" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Health row (Status / Coverage / Freshness)
// ---------------------------------------------------------------------------

interface StatusCardProps {
  source: SourceDetail
  isDbLiveSource: boolean
}

export function StatusCard({ source, isDbLiveSource }: StatusCardProps) {
  const job = source.latest_job
  const running = job?.status === 'running' || job?.status === 'pending'
  const failed = job?.status === 'failed'
  const ready = job?.status === 'success' || job?.status === 'completed'
  let dot: string
  let label: string
  let sub: string
  if (failed) {
    dot = 'bg-destructive'
    label = 'Failed'
    sub = job?.error_message?.slice(0, 80) ?? 'Last run failed.'
  } else if (running) {
    dot = 'bg-blue-500 animate-pulse'
    label = isDbLiveSource ? 'Studying…' : 'Syncing…'
    sub = job?.started_at ? `Started ${formatTimestamp(job.started_at)}` : 'In progress'
  } else if (ready && source.is_active) {
    dot = 'bg-emerald-500'
    label = 'Ready · Approved'
    sub = source.next_sync_due_at
      ? `Next sync ${formatTimestamp(source.next_sync_due_at)}`
      : 'Available to users'
  } else if (ready) {
    dot = 'bg-amber-500'
    label = 'Ready · Pending review'
    sub = 'Approve in Settings to expose to users'
  } else {
    dot = 'bg-zinc-400'
    label = 'Never run'
    sub = isDbLiveSource ? 'Click Re-study schema to start' : 'Click Sync now to start'
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <div className="flex items-center gap-2">
          <span className={cn('inline-block h-2.5 w-2.5 rounded-full', dot)} aria-hidden />
          <p className="font-medium">{label}</p>
        </div>
        <p className="text-xs text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  )
}

interface CoverageCardProps {
  source: SourceDetail
  isDbSource: boolean
  stats: { document_count: number; chunk_count: number } | undefined
}

export function CoverageCard({ source, isDbSource, stats }: CoverageCardProps) {
  let primary: string | number = '—'
  let primaryLabel: string
  let secondary: string | null = null
  if (isDbSource) {
    primary = source.tables_documented ?? '—'
    primaryLabel = primary === 1 ? 'Table documented' : 'Tables documented'
    if (source.drift_signal_count && source.drift_signal_count > 0) {
      secondary = `${source.drift_signal_count} drift signal${
        source.drift_signal_count === 1 ? '' : 's'
      }`
    }
  } else {
    primary = stats?.document_count ?? '—'
    // Per-type label — "Pages crawled" for web, "Pages indexed" for SaaS
    // connectors, "Documents indexed" for files. The previous copy lumped
    // web + connector + file under "Documents indexed" which read wrong on
    // a 200-page Confluence space.
    if (source.source_type === 'web_url') {
      primaryLabel = primary === 1 ? 'Page crawled' : 'Pages crawled'
    } else if (CONNECTOR_TYPES.has(source.source_type)) {
      primaryLabel = primary === 1 ? 'Page indexed' : 'Pages indexed'
    } else {
      primaryLabel = primary === 1 ? 'Document indexed' : 'Documents indexed'
    }
    if (stats?.chunk_count) {
      secondary = `${stats.chunk_count.toLocaleString()} chunks`
    }
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">Coverage</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <p className="text-2xl font-bold tabular-nums">{primary}</p>
        <p className="text-xs text-muted-foreground">{primaryLabel}</p>
        {secondary ? <p className="text-xs text-muted-foreground/80">{secondary}</p> : null}
      </CardContent>
    </Card>
  )
}

interface FreshnessCardProps {
  source: SourceDetail
  isDbSource: boolean
}

export function FreshnessCard({ source, isDbSource }: FreshnessCardProps) {
  const isLive = source.source_mode === 'live'
  const lastEvent = isDbSource
    ? source.last_studied_at ?? source.last_synced_at
    : source.last_synced_at
  const eventLabel = isDbSource ? 'Last studied' : 'Last synced'
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">Freshness</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {isLive ? (
          <p className="font-medium">Live</p>
        ) : (
          <p className="font-medium">{formatTimestamp(lastEvent)}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {isLive ? 'Queried at retrieval time' : eventLabel}
        </p>
        {source.sync_schedule ? (
          <p className="font-mono text-xs text-muted-foreground/80">cron: {source.sync_schedule}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Type-specific big card
// ---------------------------------------------------------------------------

interface SourceTypeOverviewProps {
  source: SourceDetail
  stats: { document_count: number; chunk_count: number } | undefined
  documents: Array<{ id: string; created_at: string; is_active: boolean }>
}

export function SourceTypeOverview({ source, stats, documents }: SourceTypeOverviewProps) {
  if (DB_TYPES.has(source.source_type)) {
    return <DatabaseTypeOverview source={source} />
  }
  if (FILE_TYPES.has(source.source_type)) {
    return <FileTypeOverview source={source} stats={stats} documents={documents} />
  }
  if (source.source_type === 'web_url') {
    return <WebTypeOverview source={source} stats={stats} />
  }
  if (CONNECTOR_TYPES.has(source.source_type)) {
    return <ConnectorTypeOverview source={source} stats={stats} />
  }
  return null
}

function DatabaseTypeOverview({ source }: { source: SourceDetail }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <DatabaseIcon className="h-4 w-4" aria-hidden />
          Connection &amp; schema
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="rounded-md border bg-muted/30 p-3 text-xs">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
            <LockIcon className="h-3.5 w-3.5" aria-hidden />
            <span className="font-medium">Read-only safety enforced</span>
          </div>
          <p className="mt-1 text-muted-foreground">
            All queries from the agent run with{' '}
            <code className="rounded bg-background px-1">default_transaction_read_only=on</code> and
            a statement timeout. The agent cannot mutate this database.
          </p>
        </div>
        {source.study_state ? (
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Studying agent</p>
            <p>
              State:{' '}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{source.study_state}</code>
            </p>
            {source.tables_documented !== null && source.tables_documented !== undefined ? (
              <p className="text-xs text-muted-foreground">
                {source.tables_documented} tables documented
                {source.tables_partial ? ` · ${source.tables_partial} partial` : null}
              </p>
            ) : null}
            {source.last_error_phase ? (
              <p className="text-xs text-destructive">
                Last error phase: {source.last_error_phase}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Schema not yet studied. Click <strong>Re-study schema</strong> in the Sync tab to start.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

interface FileTypeOverviewInnerProps {
  source: SourceDetail
  stats: { document_count: number; chunk_count: number } | undefined
  documents: Array<{ id: string; created_at: string; is_active: boolean }>
}

function FileTypeOverview({ source, stats, documents }: FileTypeOverviewInnerProps) {
  const recent = documents.slice(0, 5)
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <FileTextIcon className="h-4 w-4" aria-hidden />
          Files in this source
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>
          <strong>{stats?.document_count ?? '—'}</strong>{' '}
          {(stats?.document_count ?? 0) === 1 ? 'document' : 'documents'} indexed
          {stats?.chunk_count ? ` · ${stats.chunk_count.toLocaleString()} chunks` : null}
        </p>
        {recent.length > 0 ? (
          <div className="rounded-md border">
            <ul className="divide-y">
              {recent.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center justify-between px-3 py-2 text-xs"
                >
                  <span className="truncate font-mono text-muted-foreground" title={doc.id}>
                    {doc.id.slice(0, 12)}…
                  </span>
                  <span className="text-muted-foreground">
                    {formatTimestamp(doc.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            No documents yet. Re-upload files via the wizard to add more.
          </p>
        )}
        {source.has_upload ? (
          <p className="text-xs text-muted-foreground/80">
            Source has an associated upload archive in object storage.
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function WebTypeOverview({
  source,
  stats,
}: {
  source: SourceDetail
  stats: { document_count: number; chunk_count: number } | undefined
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <GlobeIcon className="h-4 w-4" aria-hidden />
          Crawl details
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>
          <strong>{stats?.document_count ?? '—'}</strong> pages crawled
          {stats?.chunk_count ? ` · ${stats.chunk_count.toLocaleString()} chunks` : null}
        </p>
        <p className="text-xs text-muted-foreground">
          Last crawl: {formatTimestamp(source.last_synced_at)}
        </p>
      </CardContent>
    </Card>
  )
}

function ConnectorTypeOverview({
  source,
  stats,
}: {
  source: SourceDetail
  stats: { document_count: number; chunk_count: number } | undefined
}) {
  const labelByType: Record<string, string> = {
    confluence: 'Confluence space',
    sharepoint: 'SharePoint site',
    notion: 'Notion workspace',
    google_drive: 'Google Drive folder',
  }
  const label = labelByType[source.source_type] ?? 'Workspace'
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <PlugIcon className="h-4 w-4" aria-hidden />
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>
          <strong>{stats?.document_count ?? '—'}</strong>{' '}
          {(stats?.document_count ?? 0) === 1 ? 'page' : 'pages'} indexed
          {stats?.chunk_count ? ` · ${stats.chunk_count.toLocaleString()} chunks` : null}
        </p>
        <p className="text-xs text-muted-foreground">
          Last sync: {formatTimestamp(source.last_synced_at)}
        </p>
        {source.sync_mode === 'scheduled' && source.sync_schedule ? (
          <p className="text-xs text-muted-foreground/80">
            Auto-syncs on schedule: <code>{source.sync_schedule}</code>
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
