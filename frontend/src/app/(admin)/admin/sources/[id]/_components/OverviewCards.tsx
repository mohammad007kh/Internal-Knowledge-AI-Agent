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

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useSourcePermissions } from '@/features/source-permissions/hooks/useSourcePermissions'
import type { SchemaStatus, SourceDetail } from '@/lib/api/sources'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  AlertTriangleIcon,
  CircleAlertIcon,
  DatabaseIcon,
  FileTextIcon,
  GlobeIcon,
  ListTreeIcon,
  LockIcon,
  PlugIcon,
} from 'lucide-react'

const DB_TYPES: ReadonlySet<string> = new Set([
  // 'database' is what the backend StrEnum actually emits; the dialect
  // strings are forward-compat extras (see sourceTypeMatrix.ts).
  'database',
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
    // The page renders <DatabaseOverview> directly for DB sources (with the
    // tab-jump callbacks wired). This branch is the no-callbacks fallback so
    // any legacy caller of <SourceTypeOverview> still gets a sane DB view.
    return <DatabaseOverview source={source} />
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

// ---------------------------------------------------------------------------
// Database source — enriched Overview (U10)
//
// Replaces the legacy "Connection & schema" card. Layout:
//   1. <StatusCard> (the page already renders OverviewCallouts above it).
//   2. Hero card — type icon + mode badges + AI description prose + schema
//      summary line.
//   3. Stat grid — Connection / Schema / Access (+ Retrieval) cells.
//   4. "What the agent sees" teaser — read-only blurb + schema-status branch.
//   5. Footer line — Created … by owner · Updated …
//
// All tab navigation flows through the optional `onViewSchema` /
// `onManageAccess` callbacks; `onRestudySchema` re-uses the page's sync
// mutation (re-running the pipeline for a DB source triggers the studying
// agent). When a callback is absent the corresponding link/button is hidden
// rather than rendered as a no-op.
// ---------------------------------------------------------------------------

export interface DatabaseOverviewProps {
  source: SourceDetail
  /** Passed straight through to the first stat-grid cell (<StatusCard>). */
  isDbLiveSource?: boolean
  onViewSchema?: () => void
  onManageAccess?: () => void
  onRestudySchema?: () => void
}

const SCHEMA_STATUS_LABELS: Record<SchemaStatus, string> = {
  READY: 'Documented',
  STUDYING: 'Studying…',
  STALE: 'May be stale',
  FAILED: 'Study failed',
  QUEUED: 'Queued',
}

function schemaStatusLabel(status: SchemaStatus | null | undefined): string {
  if (!status) return 'Not studied yet'
  return SCHEMA_STATUS_LABELS[status] ?? 'Not studied yet'
}

export function DatabaseOverview({
  source,
  isDbLiveSource = false,
  onViewSchema,
  onManageAccess,
  onRestudySchema,
}: DatabaseOverviewProps) {
  return (
    <div className="space-y-4" data-testid="db-overview">
      <DbHeroCard source={source} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatusCard source={source} isDbLiveSource={isDbLiveSource} />
        <ConnectionStatCard source={source} />
        <SchemaStatCard source={source} onViewSchema={onViewSchema} />
        <AccessStatCard sourceId={source.id} onManageAccess={onManageAccess} />
        <RetrievalStatCard />
      </div>
      <AgentTeaserCard
        source={source}
        onViewSchema={onViewSchema}
        onRestudySchema={onRestudySchema}
      />
      <MetaFooter source={source} />
    </div>
  )
}

// --- Hero card -------------------------------------------------------------

function DbHeroCard({ source }: { source: SourceDetail }) {
  const isLive = source.source_mode === 'live'
  const isTextToQuery = source.retrieval_mode === 'text_to_query'
  const description = source.description?.trim() ?? ''
  const pendingDescription = source.description_status === 'pending_ai'

  return (
    <Card data-testid="overview-hero">
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <DatabaseIcon className="h-4 w-4" aria-hidden />
          <span>Database source</span>
          <Badge variant="secondary" data-testid="overview-hero-source-mode">
            {isLive ? 'Live' : 'Snapshot'}
          </Badge>
          {isTextToQuery ? (
            <Badge variant="secondary" data-testid="overview-hero-retrieval-mode">
              Answers via SQL
            </Badge>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {pendingDescription ? (
          <div
            className="space-y-2"
            data-testid="overview-description-pending"
            aria-label="Generating description"
          >
            <p className="text-xs italic text-muted-foreground">Generating description…</p>
            <Skeleton className="h-3 w-full animate-pulse" />
            <Skeleton className="h-3 w-5/6 animate-pulse" />
            <Skeleton className="h-3 w-2/3 animate-pulse" />
          </div>
        ) : description.length > 0 ? (
          <div className="space-y-1" data-testid="overview-description">
            <p className="whitespace-pre-line break-words text-sm text-foreground">{description}</p>
            <DescriptionProvenanceSuffix source={source} />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground" data-testid="overview-description-empty">
            No description yet — the AI writes one after the schema study completes, or write your
            own in Settings →
          </p>
        )}
        {source.schema_summary && source.schema_summary.trim().length > 0 ? (
          <p
            className="flex items-start gap-1.5 text-xs italic text-muted-foreground"
            data-testid="overview-schema-summary"
          >
            <ListTreeIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>Schema: {source.schema_summary}</span>
          </p>
        ) : null}
        {/* Snapshot-mode DB sources re-study on a cron schedule; live ones
            never sync, so nothing renders for them. The raw cron string is
            shown verbatim — a human-readable parse is out of scope. */}
        {source.source_mode === 'snapshot' && source.sync_schedule ? (
          <p className="text-xs text-muted-foreground/80" data-testid="overview-sync-schedule">
            Synced on schedule: <code>{source.sync_schedule}</code>
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function DescriptionProvenanceSuffix({ source }: { source: SourceDetail }) {
  if (source.description_status === 'ai_set') {
    return (
      <p className="text-xs text-muted-foreground/80">
        AI-written · {formatRelative(source.updated_at)} — view provenance in Settings →
      </p>
    )
  }
  // user_set (or undefined on older payloads) → "Edited by you".
  return <p className="text-xs text-muted-foreground/80">Edited by you</p>
}

// --- Stat grid cells -------------------------------------------------------

interface StatShellProps {
  title: string
  testId: string
  children: React.ReactNode
}

function StatShell({ title, testId, children }: StatShellProps) {
  return (
    <Card data-testid={testId}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">{children}</CardContent>
    </Card>
  )
}

function ConnectionStatCard({ source }: { source: SourceDetail }) {
  const status = source.connection_status ?? 'unknown'
  const variant =
    status === 'healthy' ? 'default' : status === 'failed' ? 'destructive' : 'secondary'
  const checkedAt = source.connection_last_checked_at
  const succeeded = !source.connection_last_error
  let subline: string
  if (!checkedAt) {
    subline = 'no check recorded yet'
  } else if (succeeded) {
    subline = `checked ${formatRelative(checkedAt)} — succeeded`
  } else {
    subline = `checked ${formatRelative(checkedAt)} — failed: ${source.connection_last_error}`
  }
  return (
    <StatShell title="Connection" testId="overview-connection-stat">
      <Badge variant={variant}>{status}</Badge>
      <p
        className={cn(
          'text-xs',
          checkedAt && !succeeded ? 'text-destructive' : 'text-muted-foreground'
        )}
      >
        {subline}
      </p>
    </StatShell>
  )
}

function SchemaStatCard({
  source,
  onViewSchema,
}: {
  source: SourceDetail
  onViewSchema?: () => void
}) {
  const status = source.schema_status
  const label = schemaStatusLabel(status)
  const studying = status === 'STUDYING'
  const tablesLine =
    source.tables_documented !== null && source.tables_documented !== undefined
      ? `${source.tables_documented} table${source.tables_documented === 1 ? '' : 's'}${
          source.tables_partial ? ` · ${source.tables_partial} partial` : ''
        }`
      : null
  const studiedAgo = source.last_studied_at ? `studied ${formatRelative(source.last_studied_at)}` : null
  return (
    <StatShell title="Schema" testId="overview-schema-stat">
      <div className="flex items-center gap-2">
        {studying ? (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" aria-hidden />
        ) : null}
        <p className="font-medium">{label}</p>
      </div>
      {tablesLine ? (
        <p className="text-xs text-muted-foreground">{tablesLine}</p>
      ) : studiedAgo ? (
        <p className="text-xs text-muted-foreground">{studiedAgo}</p>
      ) : (source.drift_signal_count ?? 0) > 0 ? (
        <p className="text-xs text-muted-foreground">
          {source.drift_signal_count} drift signal{source.drift_signal_count === 1 ? '' : 's'}
        </p>
      ) : null}
      {onViewSchema ? (
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={onViewSchema}
          className="h-auto p-0 text-xs"
          data-testid="overview-schema-view-link"
        >
          View schema →
        </Button>
      ) : null}
    </StatShell>
  )
}

function AccessStatCard({
  sourceId,
  onManageAccess,
}: {
  sourceId: string
  onManageAccess?: () => void
}) {
  const { data: userIds, isLoading, isError } = useSourcePermissions(sourceId)
  const count = userIds?.length ?? 0
  return (
    <StatShell title="Access" testId="overview-access-stat">
      {isLoading ? (
        <Skeleton className="h-5 w-24" />
      ) : isError ? (
        <p className="text-xs text-muted-foreground">Couldn&apos;t load access</p>
      ) : count === 0 ? (
        <p className="text-sm font-medium text-destructive">No users granted — queryable by no one</p>
      ) : (
        <p className="text-sm font-medium">
          {count} user{count === 1 ? '' : 's'} granted
        </p>
      )}
      {onManageAccess ? (
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={onManageAccess}
          className="h-auto p-0 text-xs"
          data-testid="overview-access-manage-link"
        >
          Manage →
        </Button>
      ) : null}
    </StatShell>
  )
}

function RetrievalStatCard() {
  return (
    <StatShell title="Retrieval" testId="overview-retrieval-stat">
      <p className="text-xs text-muted-foreground">
        Live retrieval — rows queried at answer time, not indexed (no documents)
      </p>
    </StatShell>
  )
}

// --- "What the agent sees" teaser -----------------------------------------

function AgentTeaserCard({
  source,
  onViewSchema,
  onRestudySchema,
}: {
  source: SourceDetail
  onViewSchema?: () => void
  onRestudySchema?: () => void
}) {
  const status = source.schema_status
  return (
    <Card data-testid="overview-agent-teaser">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <ListTreeIcon className="h-4 w-4" aria-hidden />
          What the agent sees
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-start gap-2 rounded-md border bg-muted/30 p-3 text-xs">
          <LockIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-700 dark:text-emerald-300" aria-hidden />
          <p className="text-muted-foreground">
            <span className="font-medium text-emerald-700 dark:text-emerald-300">
              Read-only enforced
            </span>{' '}
            — the agent can&apos;t mutate this database. Queries run with a forced read-only
            transaction and a statement timeout.
          </p>
        </div>
        <AgentTeaserBody
          status={status}
          tablesDocumented={source.tables_documented}
          lastErrorPhase={source.last_error_phase}
          lastErrorMessage={source.last_error_message}
          onViewSchema={onViewSchema}
          onRestudySchema={onRestudySchema}
        />
      </CardContent>
    </Card>
  )
}

function RestudyButton({ onRestudySchema }: { onRestudySchema?: () => void }) {
  if (!onRestudySchema) return null
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onRestudySchema}
      data-testid="overview-restudy-button"
    >
      Re-study schema
    </Button>
  )
}

interface AgentTeaserBodyProps {
  status: SchemaStatus | null | undefined
  tablesDocumented: number | null | undefined
  lastErrorPhase: string | null | undefined
  lastErrorMessage: string | null | undefined
  onViewSchema?: () => void
  onRestudySchema?: () => void
}

function AgentTeaserBody({
  status,
  tablesDocumented,
  lastErrorPhase,
  lastErrorMessage,
  onViewSchema,
  onRestudySchema,
}: AgentTeaserBodyProps) {
  if (status === 'READY') {
    const n =
      tablesDocumented !== null && tablesDocumented !== undefined ? tablesDocumented : 'several'
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">
          The agent works from a documented sketch of {n}{' '}
          {tablesDocumented === 1 ? 'table' : 'tables'}.
        </p>
        {onViewSchema ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onViewSchema}
            data-testid="overview-teaser-open-schema"
          >
            Open Schema tab →
          </Button>
        ) : null}
      </div>
    )
  }
  if (status === 'FAILED') {
    const phaseClause = lastErrorPhase ? ` at phase ${lastErrorPhase}` : ''
    const errorClause = lastErrorMessage ? `: ${lastErrorMessage}` : ''
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">
          Schema study failed{phaseClause}
          {errorClause}. Fix the connection in Settings, then
        </p>
        <RestudyButton onRestudySchema={onRestudySchema} />
      </div>
    )
  }
  if (status === 'STALE') {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">
          Drift detected — re-study to refresh the agent&apos;s view.
        </p>
        <RestudyButton onRestudySchema={onRestudySchema} />
      </div>
    )
  }
  // null / QUEUED / STUDYING
  return (
    <div className="space-y-2">
      <p className="text-muted-foreground">
        Schema not studied yet — it runs automatically after the source is created or its
        credentials change. To run it now:
      </p>
      <RestudyButton onRestudySchema={onRestudySchema} />
    </div>
  )
}

// --- Footer line -----------------------------------------------------------

function MetaFooter({ source }: { source: SourceDetail }) {
  let createdLabel = '—'
  try {
    createdLabel = new Date(source.created_at).toLocaleDateString()
  } catch {
    createdLabel = source.created_at
  }
  const byClause = source.owner_email ? ` by ${source.owner_email}` : ''
  return (
    <p className="text-xs text-muted-foreground" data-testid="overview-meta-footer">
      Created {createdLabel}
      {byClause} · Updated {formatRelative(source.updated_at)}
    </p>
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
