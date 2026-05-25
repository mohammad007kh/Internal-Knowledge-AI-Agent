'use client'

/**
 * SchemaViewer — admin-only DB schema viewer (U7).
 *
 * Replaces the placeholder data-tab body for DB sources on the source
 * detail page. Renders the latest validated SchemaDocument from the
 * studying agent: header (count / dialect / studied-ago / re-study button),
 * partial-coverage banner, search + sort + sample-values toggle controls,
 * the full table list with a divider after the agent-visible 30, and a
 * footer with agent version, fingerprint, study duration, and terminal
 * state.
 *
 * Visibility rule: ALL tables are rendered. After
 * `MAX_TABLES_FOR_SKETCH = 30` we insert a divider line and continue
 * rendering greyed-out so admins can debug WHY a specific table was cut
 * from the agent's view.
 *
 * KEEP IN SYNC WITH text_to_query.py:_MAX_TABLES_FOR_SKETCH — the
 * studying agent's prompt-builder uses the same 30-table cap. Updating
 * one without the other silently desyncs the admin view from what the
 * agent actually sees.
 *
 * Sample-values toggle is session-scoped (`useState` only — never
 * persisted) so the reveal-samples audit row is emitted every time an
 * admin re-opens the page and flips it ON.
 */

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  useSchemaDocument,
  useTriggerSync,
} from '@/features/sources/hooks/useSources'
import {
  type ColumnDoc,
  type SchemaDocument,
  type SourceDetail,
  type TableDoc,
  SchemaDocumentNotFoundError,
  emitSamplesRevealedApi,
} from '@/lib/api/sources'
import { extractApiErrorMessage } from '@/lib/api-error'
import { cn } from '@/lib/utils'
import {
  AlertCircleIcon,
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  Loader2Icon,
  RefreshCwIcon,
} from 'lucide-react'
import { useState } from 'react'

// KEEP IN SYNC WITH text_to_query.py:_MAX_TABLES_FOR_SKETCH (30).
// Tables beyond this index are not rendered into the agent's schema sketch
// prompt; we still show them in the viewer so admins can see what was cut.
const MAX_TABLES_FOR_SKETCH = 30

type SortMode = 'name' | 'rows-desc' | 'cols-desc'

export interface SchemaViewerProps {
  sourceId: string
  /**
   * Optional source detail used to differentiate the four "non-ready"
   * states the schema-document endpoint alone cannot tell apart:
   *
   *   - never studied (`schema_status` null / 'PENDING') → empty state
   *   - studying right now (`'QUEUED'` / `'STUDYING'`)   → spinner
   *   - last run failed (`'FAILED'`)                      → error + phase
   *   - studied but found zero tables                     → empty-DB hint
   *
   * Backwards compatible: when omitted, the component falls back to its
   * pre-FX18 behaviour (404 → empty, anything else → generic error).
   */
  source?: SourceDetail | null
}

/**
 * Top-level viewer. Owns the sample-values toggle, search input, sort
 * mode, and per-row expansion state.
 */
export function SchemaViewer({ sourceId, source }: SchemaViewerProps) {
  const schemaStatus = source?.schema_status ?? null
  const studyState = source?.study_state ?? null
  // Studying / queued are short-circuited *before* the React Query result so
  // the spinner appears immediately even on a cold cache. The parent page's
  // `useSource(..., { pollWhileRunning: 'auto' })` already polls every 3s
  // while these states are active, so the tab auto-flips when ready.
  // FX41 — schema_status is lowercase on the wire; the 'queued before any
  // work' state lives on study_state (uppercase QUEUED).
  const isStudying = schemaStatus === 'studying' || studyState === 'QUEUED'
  // Failed is also short-circuited: we render the error UI from the source
  // detail's `last_error_*` fields and never hit the schema-document endpoint
  // (it would return either a stale doc from a previous successful run or a
  // 404 — neither is helpful here).
  const isKnownFailed = schemaStatus === 'failed'

  // Don't fire the schema-document fetch while the studying agent is still
  // running or the last run failed — both branches render without needing
  // the document payload.
  const query = useSchemaDocument(sourceId, {
    enabled: !isStudying && !isKnownFailed,
  })
  const triggerSync = useTriggerSync()

  // Session-scoped — explicitly NOT persisted to localStorage so the audit
  // row fires on every fresh page load when an admin reveals samples.
  const [showSamples, setShowSamples] = useState<boolean>(false)
  const [search, setSearch] = useState<string>('')
  const [sortMode, setSortMode] = useState<SortMode>('name')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  // --- State branching --------------------------------------------------
  // Order is intentional: studying beats failed (the next run might already
  // be in flight); failed beats not-yet-documented; document-with-zero-tables
  // beats default empty (we have a real answer, just no rows).

  if (isStudying) {
    return <SchemaStudyingState />
  }

  if (isKnownFailed) {
    return (
      <SchemaFailedState
        phase={source?.last_error_phase ?? null}
        message={source?.last_error_message ?? null}
        onRestudy={() => triggerSync.mutate(sourceId)}
        restudying={triggerSync.isPending}
      />
    )
  }

  if (query.isPending) {
    return <SchemaViewerSkeleton />
  }

  if (query.isError) {
    // 404 → "not yet studied". `getSchemaDocumentApi` re-throws as the typed
    // SchemaDocumentNotFoundError so we don't have to parse strings here.
    if (query.error instanceof SchemaDocumentNotFoundError) {
      return (
        <SchemaNotYetDocumented
          onRestudy={() => triggerSync.mutate(sourceId)}
          restudying={triggerSync.isPending}
        />
      )
    }
    // Anything else is a real fetch error — surface the backend's message.
    return (
      <SchemaFailedState
        phase={null}
        message={extractApiErrorMessage(query.error)}
        onRestudy={() => void query.refetch()}
        restudying={query.isFetching}
        retryLabel="Retry"
      />
    )
  }

  const doc = query.data.schema_document

  // The studying agent completed but introspection returned zero tables.
  // Likely cause: pointed at an empty database or one the credentials
  // can't see. Surface a distinct empty state rather than the
  // unfiltered-empty-list look further down.
  if (doc.tables.length === 0) {
    return (
      <SchemaEmptyDatabase
        dialect={doc.dialect}
        onRestudy={() => triggerSync.mutate(sourceId)}
        restudying={triggerSync.isPending}
      />
    )
  }

  const visibleTables = filterAndSortTables(doc.tables, search, sortMode)

  const handleToggleSamples = (next: boolean): void => {
    setShowSamples(next)
    if (next) {
      // Fire-and-forget — never block the toggle UI on the audit emit.
      // We swallow the error because the audit endpoint is best-effort
      // from the admin's perspective.
      void emitSamplesRevealedApi(sourceId).catch(() => {
        /* noop — audit is best-effort */
      })
    }
  }

  return (
    <div data-testid="schema-viewer" className="space-y-4">
      <Card>
        <CardHeader className="space-y-2">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="text-base">
                Schema{' '}
                <span className="text-sm font-normal text-muted-foreground">
                  ({doc.tables.length}{' '}
                  {doc.tables.length === 1 ? 'table' : 'tables'} ·{' '}
                  {doc.dialect} · studied{' '}
                  {formatRelativeFromNow(doc.generated_at)})
                </span>
              </CardTitle>
              {doc.summary ? (
                <p
                  className="text-sm text-muted-foreground"
                  data-testid="schema-summary"
                >
                  {doc.summary}
                </p>
              ) : null}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => triggerSync.mutate(sourceId)}
              disabled={triggerSync.isPending}
              data-testid="schema-restudy-button"
            >
              <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              Re-study
            </Button>
          </div>

          {doc.truncated_at != null && doc.truncated_at > doc.tables.length ? (
            <TruncationBanner
              totalSeen={doc.truncated_at}
              shown={doc.tables.length}
            />
          ) : null}
          {doc.partial_coverage &&
          doc.skipped_tables &&
          doc.skipped_tables.length > 0 ? (
            <SkippedTablesBanner skippedTables={doc.skipped_tables} />
          ) : null}
          {doc.llm_descriptions_available === false ? (
            <LlmDescriptionsUnavailableBanner />
          ) : null}
          {doc.partial ? (
            <PartialCoverageBanner phaseErrors={doc.phase_errors} />
          ) : null}
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 border-b pb-3">
            <div className="flex-1 min-w-[200px]">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter tables…"
                aria-label="Filter tables by name"
                data-testid="schema-filter-input"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Sort</span>
              <Select
                value={sortMode}
                onValueChange={(v) => setSortMode(v as SortMode)}
              >
                <SelectTrigger
                  className="h-9 w-[180px]"
                  data-testid="schema-sort-select"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="name">Name (A→Z)</SelectItem>
                  <SelectItem value="rows-desc">Row count (high→low)</SelectItem>
                  <SelectItem value="cols-desc">Column count (high→low)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <Switch
                      checked={showSamples}
                      onCheckedChange={handleToggleSamples}
                      aria-label="Show sample values"
                      data-testid="schema-samples-toggle"
                    />
                    <span>Show sample values</span>
                  </label>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[260px]">
                  Reveal recorded sample values for every column. Each
                  reveal is logged to the admin audit trail.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          <ul className="divide-y rounded-md border" data-testid="schema-table-list">
            {visibleTables.map((row) => (
              <li key={`${row.position}-${row.table.name}`}>
                {row.dividerBefore ? (
                  <div
                    className="bg-muted/40 px-3 py-2 text-xs italic text-muted-foreground"
                    data-testid="schema-truncation-divider"
                  >
                    ── Below this line: not visible to the agent ───────────
                  </div>
                ) : null}
                <SchemaTableRow
                  table={row.table}
                  hidden={row.hiddenFromAgent}
                  expanded={Boolean(expanded[row.table.name])}
                  onToggle={() =>
                    setExpanded((prev) => ({
                      ...prev,
                      [row.table.name]: !prev[row.table.name],
                    }))
                  }
                  showSamples={showSamples}
                />
              </li>
            ))}
            {visibleTables.length === 0 ? (
              <li className="px-3 py-4 text-center text-sm text-muted-foreground">
                No tables match the filter.
              </li>
            ) : null}
          </ul>
        </CardContent>
      </Card>

      <SchemaFooter doc={doc} state={query.data.state} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Loading / empty / error sub-components
// ---------------------------------------------------------------------------

function SchemaViewerSkeleton() {
  return (
    <Card data-testid="schema-viewer-loading">
      <CardHeader>
        <Skeleton className="h-5 w-72" />
        <Skeleton className="h-3 w-full max-w-md" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </CardContent>
    </Card>
  )
}

interface RestudyActionProps {
  onRestudy: () => void
  restudying: boolean
  label?: string
}

function RestudyAction({ onRestudy, restudying, label = 'Run schema study' }: RestudyActionProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onRestudy}
      disabled={restudying}
      data-testid="schema-restudy-action"
    >
      <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden />
      {restudying ? 'Starting…' : label}
    </Button>
  )
}

interface SchemaNotYetDocumentedProps {
  onRestudy: () => void
  restudying: boolean
}

function SchemaNotYetDocumented({ onRestudy, restudying }: SchemaNotYetDocumentedProps) {
  return (
    <div
      className="space-y-3 rounded-md border bg-muted/20 p-6 text-sm"
      data-testid="schema-empty-state"
    >
      <p className="font-medium">This source hasn&apos;t been studied yet.</p>
      <p className="text-xs text-muted-foreground">
        The AI catalogs the schema on first sync — trigger a study or run a
        sync to populate it.
      </p>
      <RestudyAction onRestudy={onRestudy} restudying={restudying} />
    </div>
  )
}

function SchemaStudyingState() {
  return (
    <div
      className="space-y-3 rounded-md border bg-muted/20 p-6 text-sm"
      data-testid="schema-studying-state"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 font-medium">
        <Loader2Icon
          className="h-4 w-4 animate-spin text-muted-foreground"
          aria-hidden
        />
        <span>The AI is studying the schema right now.</span>
      </div>
      <p className="text-xs text-muted-foreground">
        This usually takes 10–30s. The page will refresh automatically when
        it&apos;s ready.
      </p>
      <div className="space-y-2 pt-1">
        <Skeleton className="h-3 w-full max-w-md" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    </div>
  )
}

interface SchemaFailedStateProps {
  phase: string | null
  message: string | null
  onRestudy: () => void
  restudying: boolean
  retryLabel?: string
}

function SchemaFailedState({
  phase,
  message,
  onRestudy,
  restudying,
  retryLabel = 'Re-study schema',
}: SchemaFailedStateProps) {
  return (
    <div
      className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-6 text-sm"
      data-testid="schema-failed-state"
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertCircleIcon
          className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
          aria-hidden
        />
        <div className="space-y-1">
          <p className="font-medium text-destructive">Schema study failed.</p>
          {phase ? (
            <p
              className="text-xs text-muted-foreground"
              data-testid="schema-failed-phase"
            >
              Failed during phase <span className="font-mono">{phase}</span>.
            </p>
          ) : null}
          {message ? (
            <p
              className="break-words text-xs text-muted-foreground"
              data-testid="schema-failed-message"
            >
              {message}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              No details reported by the studying agent.
            </p>
          )}
        </div>
      </div>
      <RestudyAction
        onRestudy={onRestudy}
        restudying={restudying}
        label={retryLabel}
      />
    </div>
  )
}

interface SchemaEmptyDatabaseProps {
  dialect: string
  onRestudy: () => void
  restudying: boolean
}

function SchemaEmptyDatabase({
  dialect,
  onRestudy,
  restudying,
}: SchemaEmptyDatabaseProps) {
  return (
    <div
      className="space-y-3 rounded-md border bg-muted/20 p-6 text-sm"
      data-testid="schema-empty-database-state"
    >
      <p className="font-medium">
        The studying agent found no tables in the connected database.
      </p>
      <p className="text-xs text-muted-foreground">
        The {dialect} connection succeeded, but the studying agent didn&apos;t
        see any user tables. Double-check the connection — particularly the
        database name and schema search path — to make sure you pointed at
        the right database, then re-run the study.
      </p>
      <RestudyAction
        onRestudy={onRestudy}
        restudying={restudying}
        label="Re-study schema"
      />
    </div>
  )
}

interface TruncationBannerProps {
  totalSeen: number
  shown: number
}

/**
 * Surfaced when the source reported more relations than the per-source
 * cap. Distinct from {@link PartialCoverageBanner} (per-phase errors) and
 * {@link SkippedTablesBanner} (named tables we couldn't include) — this is
 * "we deliberately stopped at N because the source is huge".
 */
function TruncationBanner({ totalSeen, shown }: TruncationBannerProps) {
  return (
    <div
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      data-testid="schema-truncation-banner"
      role="status"
    >
      <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">
          Large schema — showing {shown} of {totalSeen} tables
        </p>
        <p>
          The studying agent capped the study at {shown} tables. The remaining{' '}
          {totalSeen - shown} are not in the schema document — narrow the
          source (e.g. limit the schema search path) and re-study to cover
          them.
        </p>
      </div>
    </div>
  )
}

interface SkippedTablesBannerProps {
  skippedTables: ReadonlyArray<string>
}

/**
 * Surfaced when the studying agent skipped one or more named tables
 * (typically permission-denied — admin credentials can list the table but
 * not read its columns or rows). Layered ON TOP of READY: the doc itself
 * is fine; this just enumerates what's missing.
 */
function SkippedTablesBanner({ skippedTables }: SkippedTablesBannerProps) {
  return (
    <div
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      data-testid="schema-skipped-tables-banner"
      role="status"
    >
      <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">
          Partial coverage — {skippedTables.length} table
          {skippedTables.length === 1 ? '' : 's'} skipped
        </p>
        <p>
          The studying agent could not include these tables (usually because
          the connection user lacks SELECT on them). Grant the missing
          permissions and re-study to cover them.
        </p>
        <ul className="list-disc space-y-0.5 pl-4 font-mono">
          {skippedTables.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/**
 * Surfaced when the LLM stage produced no usable descriptions for any
 * table. The schema metadata is the load-bearing part — descriptions are
 * gravy — but admins should know AI blurbs are missing so they don't
 * assume the agent forgot.
 */
function LlmDescriptionsUnavailableBanner() {
  return (
    <div
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      data-testid="schema-llm-unavailable-banner"
      role="status"
    >
      <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">AI descriptions unavailable</p>
        <p>
          The schema is complete, but the studying agent could not generate
          per-table descriptions (typically a temporary LLM outage). Schema
          metadata is unaffected. Re-study later to fill in the blurbs.
        </p>
      </div>
    </div>
  )
}

interface PartialCoverageBannerProps {
  phaseErrors: ReadonlyArray<{ phase: string; message: string }>
}

function PartialCoverageBanner({ phaseErrors }: PartialCoverageBannerProps) {
  return (
    <div
      className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      data-testid="schema-partial-banner"
      role="status"
    >
      <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">
          Partial coverage — {phaseErrors.length}{' '}
          {phaseErrors.length === 1 ? 'phase' : 'phases'} failed
        </p>
        <ul className="list-disc space-y-0.5 pl-4">
          {phaseErrors.map((err, idx) => (
            <li key={`${err.phase}-${idx}`}>
              <span className="font-mono">{err.phase}</span>: {err.message}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-table row
// ---------------------------------------------------------------------------

interface SchemaTableRowProps {
  table: TableDoc
  hidden: boolean
  expanded: boolean
  onToggle: () => void
  showSamples: boolean
}

function SchemaTableRow({
  table,
  hidden,
  expanded,
  onToggle,
  showSamples,
}: SchemaTableRowProps) {
  return (
    <div
      className={cn(
        'px-3 py-2',
        hidden && 'opacity-50',
      )}
      data-testid={hidden ? 'schema-table-row-hidden' : 'schema-table-row'}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 text-left text-sm hover:bg-muted/40"
      >
        {expanded ? (
          <ChevronDownIcon className="h-4 w-4 shrink-0" aria-hidden />
        ) : (
          <ChevronRightIcon className="h-4 w-4 shrink-0" aria-hidden />
        )}
        <span
          className={cn(
            'font-mono text-sm',
            hidden && 'line-through decoration-muted-foreground/60',
          )}
        >
          {table.name}
        </span>
        <Badge variant="secondary" className="text-[10px]">
          {table.kind}
        </Badge>
        {table.primary_key.length > 0 ? (
          <Badge variant="outline" className="text-[10px]">
            PK: {table.primary_key.join(', ')}
          </Badge>
        ) : null}
        <span className="text-xs text-muted-foreground">
          {table.columns.length}{' '}
          {table.columns.length === 1 ? 'col' : 'cols'}
        </span>
        {table.row_count_estimate !== null &&
        table.row_count_estimate !== undefined ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            ~{formatRowCount(table.row_count_estimate)} rows
          </span>
        ) : null}
        {table.tags.map((tag) => (
          <Badge key={tag} variant="outline" className="text-[10px]">
            {tag}
          </Badge>
        ))}
      </button>

      {expanded ? (
        <div
          className="mt-2 space-y-3 border-t pt-2"
          data-testid="schema-table-expanded"
        >
          {table.description ? (
            <p className="text-sm italic text-muted-foreground">
              {table.description}
            </p>
          ) : null}

          <ColumnsTable columns={table.columns} showSamples={showSamples} />

          {table.indexes.length > 0 ? (
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">
                Indexes
              </p>
              <ul
                className="space-y-1 text-xs"
                data-testid="schema-indexes-list"
              >
                {table.indexes.map((idx) => (
                  <li key={idx.name} className="flex items-center gap-2">
                    <span className="font-mono">{idx.name}</span>
                    <span className="text-muted-foreground">
                      ({idx.columns.join(', ')})
                    </span>
                    {idx.unique ? (
                      <Badge variant="outline" className="text-[10px]">
                        unique
                      </Badge>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {table.relationships.length > 0 ? (
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">
                Relationships
              </p>
              <ul
                className="space-y-1 text-xs"
                data-testid="schema-relationships-list"
              >
                {table.relationships.map((rel, idx) => (
                  <li
                    key={`${rel.to_table}-${idx}`}
                    className="flex flex-wrap items-center gap-1 font-mono"
                  >
                    <span>({rel.from_columns.join(', ')})</span>
                    <span>→</span>
                    <span>{rel.to_table}</span>
                    <span>({rel.to_columns.join(', ')})</span>
                    <Badge variant="outline" className="text-[10px]">
                      {rel.kind}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

interface ColumnsTableProps {
  columns: ReadonlyArray<ColumnDoc>
  showSamples: boolean
}

function ColumnsTable({ columns, showSamples }: ColumnsTableProps) {
  return (
    <div className="overflow-x-auto" data-testid="schema-columns-table">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-1 pr-3 font-medium">Name</th>
            <th className="py-1 pr-3 font-medium">Type</th>
            <th className="py-1 pr-3 font-medium">Modifiers</th>
            {showSamples ? (
              <th className="py-1 pr-3 font-medium">Sample values</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {columns.map((col) => (
            <tr key={col.name} className="border-b last:border-0">
              <td className="py-1 pr-3 font-mono">
                <div className="flex items-center gap-1.5">
                  <span>{col.name}</span>
                  {col.is_pii_candidate ? (
                    <Badge
                      variant="destructive"
                      className="text-[10px]"
                      data-testid="schema-pii-chip"
                    >
                      PII
                    </Badge>
                  ) : null}
                </div>
              </td>
              <td className="py-1 pr-3 font-mono text-muted-foreground">
                {col.type}
              </td>
              <td className="py-1 pr-3 text-muted-foreground">
                {renderModifiers(col)}
              </td>
              {showSamples ? (
                <td
                  className="py-1 pr-3 font-mono text-muted-foreground"
                  data-testid="schema-sample-values"
                >
                  {col.sample_values.length === 0
                    ? '—'
                    : col.sample_values.join(', ')}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderModifiers(col: ColumnDoc): string {
  const parts: string[] = []
  if (!col.nullable) parts.push('NOT NULL')
  if (col.default !== null) parts.push(`default=${col.default}`)
  if (col.inferred) parts.push('inferred')
  return parts.join(' · ') || '—'
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------

interface SchemaFooterProps {
  doc: SchemaDocument
  state: string
}

function SchemaFooter({ doc, state }: SchemaFooterProps) {
  return (
    <p
      className="text-xs text-muted-foreground"
      data-testid="schema-footer"
    >
      Studied by agent v{doc.agent_version} · fingerprint{' '}
      <span className="font-mono">{doc.fingerprint.slice(0, 8)}</span> ·{' '}
      {formatDuration(doc.study_duration_ms)} · {state}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Helpers — pure, easy to unit-test in isolation if needed
// ---------------------------------------------------------------------------

interface RenderedRow {
  table: TableDoc
  position: number
  /** True for the first row whose original position was >= MAX_TABLES_FOR_SKETCH. */
  dividerBefore: boolean
  /** True when the row's original position was >= MAX_TABLES_FOR_SKETCH. */
  hiddenFromAgent: boolean
}

/**
 * Apply the search filter, then sort by the requested mode while
 * preserving the agent-truncation marker (rows past index 30 stay flagged
 * even after sort) and inserting a single divider before the first
 * agent-hidden row in the *rendered* sequence.
 *
 * The "hiddenFromAgent" flag is computed against the ORIGINAL table list
 * (before sort + filter) — that's the contract we share with
 * `text_to_query._render_schema_sketch`. After sort, the divider may
 * appear at any position; if no hidden row matches the filter, no
 * divider renders.
 */
function filterAndSortTables(
  tables: ReadonlyArray<TableDoc>,
  search: string,
  sortMode: SortMode,
): RenderedRow[] {
  const needle = search.trim().toLowerCase()
  const matched: RenderedRow[] = []
  tables.forEach((table, originalIdx) => {
    if (needle && !table.name.toLowerCase().includes(needle)) return
    matched.push({
      table,
      position: originalIdx,
      dividerBefore: false,
      hiddenFromAgent: originalIdx >= MAX_TABLES_FOR_SKETCH,
    })
  })

  matched.sort((a, b) => {
    switch (sortMode) {
      case 'rows-desc':
        return (b.table.row_count_estimate ?? -1) -
          (a.table.row_count_estimate ?? -1)
      case 'cols-desc':
        return b.table.columns.length - a.table.columns.length
      case 'name':
      default:
        return a.table.name.localeCompare(b.table.name)
    }
  })

  // Mark the first agent-hidden row (in the post-sort order) as the
  // divider anchor. When sorted by name (default), this falls between
  // index 29 and 30 of the original list — exactly the spec.
  for (const row of matched) {
    if (row.hiddenFromAgent) {
      row.dividerBefore = true
      break
    }
  }
  return matched
}

function formatRowCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

function formatDuration(ms: number): string {
  if (ms < 1_000) return `${ms}ms`
  return `${(ms / 1_000).toFixed(1)}s`
}

function formatRelativeFromNow(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'recently'
  const seconds = Math.max(1, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

