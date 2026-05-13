'use client'

import { ErrorState } from '@/components/ui/ErrorState'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PermissionsManager } from '@/app/(admin)/admin/sources/[id]/permissions/_components/PermissionsManager'
import { AINamingCard } from '@/app/(admin)/admin/sources/[id]/_components/AINamingCard'
import { EditCredentialsDialog } from '@/app/(admin)/admin/sources/[id]/_components/EditCredentialsDialog'
import { SchemaViewer } from '@/app/(admin)/admin/sources/[id]/_components/SchemaViewer'
import {
  CoverageCard,
  DatabaseOverview,
  FreshnessCard,
  OverviewCallouts,
  SourceTypeOverview,
  StatusCard,
} from '@/app/(admin)/admin/sources/[id]/_components/OverviewCards'
import { SyncStatusPill } from '@/app/(admin)/admin/sources/[id]/_components/SyncStatusPill'
import { TestTab } from '@/app/(admin)/admin/sources/[id]/_components/TestTab'
import { useSyncJobToast } from '@/app/(admin)/admin/sources/[id]/_components/useSyncJobToast'
import {
  type FormFieldConfig,
  dataNounFor,
  dataTabLabelFor,
  emptyDataCopyFor,
  getEditableFieldsFor,
  sourceKindOf,
} from '@/app/(admin)/admin/sources/[id]/_components/sourceTypeMatrix'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Textarea } from '@/components/ui/textarea'
import {
  useDeleteSource,
  usePhaseTransitionInvalidation,
  useSource,
  useSourceDocuments,
  useSourceStats,
  useSyncJobs,
  useTestConnection,
  useTriggerSync,
  useUpdateSource,
} from '@/features/sources/hooks/useSources'
import { AvailabilityToggle } from '@/features/sources/components/AvailabilityToggle'
import { LifecycleProgressBar } from '@/features/sources/components/LifecycleProgressBar'
import { LifecycleStepper } from '@/features/sources/components/LifecycleStepper'
import { useLifecycle } from '@/features/sources/lifecycle'
import {
  SourceModeBadge,
  StatusBadge,
  SyncModeBadge,
  formatTimestamp,
} from '@/features/sources/source-ui'
import type {
  RetrievalMode,
  SourceDetail,
  SourceMode,
  SourceType,
  SyncJob,
  SyncMode,
  UpdateSourceRequest,
} from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Loader2Icon,
  LockIcon,
  PlugIcon,
  RefreshCwIcon,
  Trash2Icon,
  XCircleIcon,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

// ---------------------------------------------------------------------------
// Pagination + form constants
// ---------------------------------------------------------------------------

const SYNC_JOBS_PAGE_SIZE = 20

/**
 * Retrieval modes shown in the editable Settings form.
 *
 * `hybrid` is intentionally excluded — it's deprecated from the form even
 * though it's still in the wire enum (forward compat). Sources persisted
 * with `retrieval_mode: 'hybrid'` will still load — the Select renders
 * the saved value as a chip — but no admin can pick it from the dropdown.
 */
const RETRIEVAL_MODES_EDITABLE: readonly RetrievalMode[] = ['vector_only', 'text_to_query']
const SOURCE_MODES: readonly SourceMode[] = ['snapshot', 'live']

const RETRIEVAL_MODE_LABELS: Record<RetrievalMode, string> = {
  vector_only: 'Vector search',
  text_to_query: 'Text to query',
  hybrid: 'Hybrid',
}

const SYNC_MODE_LABELS: Record<SyncMode, string> = {
  manual: 'Manual',
  scheduled: 'Scheduled',
  delta: 'Delta',
}

const SOURCE_MODE_LABELS: Record<SourceMode, string> = {
  snapshot: 'Snapshot',
  live: 'Live',
}

/**
 * Source types that expose a "Test connection" affordance on the detail page.
 *
 * File-based sources have no remote connection to probe — the bytes already
 * live in MinIO, so the button is hidden. Database, web, and SaaS connector
 * sources all do something useful when probed.
 */
const CONNECTION_TESTABLE_TYPES: ReadonlySet<SourceType> = new Set<SourceType>([
  'postgresql',
  'mysql',
  'mssql',
  'mongodb',
  'web_url',
  'confluence',
  'sharepoint',
  'google_drive',
  'notion',
])

function isConnectionTestable(sourceType: SourceType): boolean {
  return CONNECTION_TESTABLE_TYPES.has(sourceType)
}

// ---------------------------------------------------------------------------
// Edit form schema (Settings tab)
//
// `sync_schedule` is required only when `sync_mode === 'scheduled'`. We model
// this with a discriminated superRefine so the error attaches cleanly to the
// schedule field.
// ---------------------------------------------------------------------------

const editSchema = z
  .object({
    name: z
      .string()
      .min(1, 'Name is required')
      .max(255, 'Max 255 characters')
      .refine((value) => !value.includes('/'), {
        message: 'Name cannot contain a forward slash',
      }),
    description: z.string().max(2000, 'Max 2000 characters'),
    retrieval_mode: z.enum(['vector_only', 'text_to_query', 'hybrid']),
    sync_mode: z.enum(['manual', 'scheduled', 'delta']),
    sync_schedule: z.string(),
    source_mode: z.enum(['snapshot', 'live']),
  })
  .superRefine((values, ctx) => {
    if (values.sync_mode === 'scheduled' && values.sync_schedule.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['sync_schedule'],
        message: 'Cron schedule is required when sync mode is "scheduled"',
      })
    }
  })

type EditFormValues = z.infer<typeof editSchema>

function sourceToFormValues(source: SourceDetail): EditFormValues {
  return {
    name: source.name,
    description: source.description ?? '',
    retrieval_mode: source.retrieval_mode,
    sync_mode: source.sync_mode,
    sync_schedule: source.sync_schedule ?? '',
    source_mode: source.source_mode,
  }
}

/**
 * Diff form values against the current source and return only the changed
 * fields. The PATCH endpoint accepts partial bodies, so sending only dirty
 * fields keeps us from overwriting state we never touched.
 *
 * Special case: `sync_schedule` is sent as `null` (not empty string) when the
 * sync mode flips to anything other than 'scheduled', so the backend can
 * clear any prior cron expression.
 */
function diffSourceUpdate(
  source: SourceDetail,
  values: EditFormValues
): UpdateSourceRequest {
  const patch: UpdateSourceRequest = {}

  if (values.name !== source.name) {
    patch.name = values.name
  }

  const trimmedDescription = values.description.trim()
  const currentDescription = source.description ?? ''
  if (trimmedDescription !== currentDescription) {
    // Empty string means the user cleared the field — encode as null so the
    // backend stores NULL rather than an empty string sentinel.
    patch.description = trimmedDescription.length === 0 ? null : trimmedDescription
  }

  if (values.retrieval_mode !== source.retrieval_mode) {
    patch.retrieval_mode = values.retrieval_mode
  }

  if (values.sync_mode !== source.sync_mode) {
    patch.sync_mode = values.sync_mode
  }

  // For `sync_schedule`: only include when the *effective* schedule differs
  // from what's persisted. When sync_mode is not 'scheduled' the effective
  // schedule is null regardless of what the user typed.
  const effectiveSchedule =
    values.sync_mode === 'scheduled' ? values.sync_schedule.trim() : null
  const currentSchedule = source.sync_schedule ?? null
  if (effectiveSchedule !== currentSchedule) {
    patch.sync_schedule = effectiveSchedule
  }

  if (values.source_mode !== source.source_mode) {
    patch.source_mode = values.source_mode
  }

  return patch
}

export default function SourceDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [syncJobsPage, setSyncJobsPage] = useState(0)
  const [activeTab, setActiveTab] = useState('overview')

  // --- Smart polling (U2) ---
  // The detail query auto-polls every 3s whenever its own cached data shows
  // `latest_job.status` in `{pending, running}`. The 'auto' mode reads the
  // status off the cache via React Query's `refetchInterval(query)` callback,
  // so we don't need a separate trigger.
  const {
    data: source,
    isLoading,
    isError,
    error,
    refetch,
  } = useSource(id, { pollWhileRunning: 'auto' })
  const isJobInFlight =
    source?.latest_job?.status === 'pending' ||
    source?.latest_job?.status === 'running'

  const syncJobsData = useSyncJobs(id, {
    limit: SYNC_JOBS_PAGE_SIZE,
    offset: syncJobsPage * SYNC_JOBS_PAGE_SIZE,
    pollWhileRunning: isJobInFlight,
  }).data

  const stats = useSourceStats(id).data
  const { data: documentsData } = useSourceDocuments(id)

  // U14 — derive lifecycle phase + gate matrix. The hook safely handles a
  // null source (returns an "everything disabled" state) so we can call it
  // unconditionally and pass undefined while loading.
  const lifecycle = useLifecycle(source ?? null)

  // U14 — when the phase changes (e.g. running → ready), invalidate sibling
  // queries so the source list, chat session picker, and stats refresh
  // without a manual reload.
  usePhaseTransitionInvalidation(id, lifecycle.phase)

  const syncMutation = useTriggerSync()
  const testConnectionMutation = useTestConnection()
  const deleteMutation = useDeleteSource()
  const updateMutation = useUpdateSource(id)

  const [confirmDelete, setConfirmDelete] = useState(false)

  // Session-scoped set of job IDs the admin started in this tab. Beat-driven
  // jobs that arrive on the wire are NOT in this set, so the toast hook stays
  // silent on success for them. Failure toasts ALWAYS fire regardless.
  const sessionTriggeredJobIdsRef = useRef<Set<string>>(new Set())

  // Smart-toast hook: fires once per terminal transition. Hooks must be
  // called unconditionally — pass `null` until the source has loaded.
  // `sourceKindOf` handles the backend's real 'database' value (the local
  // dialect-name set this used to check never matched — see FX6).
  const isDbLiveSource = source
    ? sourceKindOf(source.source_type) === 'database' &&
      (source.source_mode === 'live' || source.retrieval_mode === 'text_to_query')
    : false

  useSyncJobToast({
    sourceId: id ?? '',
    latestJob: source?.latest_job ?? null,
    sessionTriggeredJobIds: sessionTriggeredJobIdsRef.current,
    isDbLiveSource,
    onViewError: () => {
      // Switch to the Sync tab so the row is visible. Scrolling exact rows
      // requires a row-id ref map we don't yet maintain — surfacing the tab
      // is enough for v1.
      setActiveTab('sync')
    },
  })

  if (isLoading) {
    return (
      <div className="space-y-4 p-4 md:space-y-6 md:p-6">
        <Skeleton className="h-4 w-48" />
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-96" />
          </div>
          <Skeleton className="h-9 w-28" />
        </div>
        <Skeleton className="h-10 w-full max-w-sm" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (isError || !source) {
    return (
      <div className="p-4 md:p-6">
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      </div>
    )
  }

  const syncJobs = syncJobsData?.items ?? []
  const syncJobsTotal = syncJobsData?.total ?? 0
  const documents = documentsData?.items ?? []

  // For text-to-query / live-DB sources, "Sync now" is a category error —
  // there are no documents to ingest. Re-running the pipeline triggers the
  // studying-agent to refresh the schema document. Re-label the action and
  // the Sync History heading accordingly.
  const isDbSource = sourceKindOf(source.source_type) === 'database'

  function trackSessionJob(job: SyncJob) {
    sessionTriggeredJobIdsRef.current.add(job.id)
  }

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      {/* Breadcrumb */}
      <nav
        className="flex items-center gap-1 text-sm text-muted-foreground"
        aria-label="Breadcrumb"
      >
        <Link href="/admin/sources" className="hover:text-foreground hover:underline">
          Sources
        </Link>
        <ChevronRightIcon className="h-4 w-4" aria-hidden />
        <span className="font-medium text-foreground">{source.name}</span>
      </nav>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="break-words text-xl font-bold md:text-2xl">{source.name}</h1>
            <Badge
              variant={source.is_active ? 'default' : 'secondary'}
              aria-label={
                source.is_active
                  ? 'Source is approved and available to users'
                  : 'Source is pending admin review'
              }
            >
              {source.is_active ? 'Available' : 'Pending review'}
            </Badge>
            <SyncStatusPill source={source} isDbLiveSource={isDbLiveSource} />
          </div>
          {source.description && (
            <p className="text-sm text-muted-foreground">{source.description}</p>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={source.status} />
            <TooltipProvider delayDuration={150}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        syncMutation.mutate(id, {
                          onSuccess: (job) => {
                            trackSessionJob(job)
                            toast.success('Sync started')
                          },
                          onError: (err) => toast.error(getErrorMessage(err)),
                        })
                      }
                      disabled={syncMutation.isPending || !lifecycle.canSyncNow}
                      aria-label={
                        isDbLiveSource
                          ? `Re-study schema for ${source.name}`
                          : `Sync source ${source.name}`
                      }
                      data-testid="header-sync-now"
                    >
                      <RefreshCwIcon className="mr-1.5 h-4 w-4" />
                      {isDbLiveSource ? 'Re-study schema' : 'Sync now'}
                    </Button>
                  </span>
                </TooltipTrigger>
                {!lifecycle.canSyncNow && lifecycle.syncNowReason ? (
                  <TooltipContent side="bottom" className="max-w-[260px] text-xs">
                    {lifecycle.syncNowReason}
                  </TooltipContent>
                ) : null}
              </Tooltip>
            </TooltipProvider>
            {isConnectionTestable(source.source_type) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  testConnectionMutation.mutate(id, {
                    onSuccess: (data) => {
                      if (data.success) toast.success(data.message || 'Connection succeeded')
                      else toast.error(data.message || 'Connection failed')
                    },
                  })
                }
                disabled={testConnectionMutation.isPending}
                aria-label={`Test connection for ${source.name}`}
                data-testid="header-test-connection"
              >
                {testConnectionMutation.isPending ? (
                  <>
                    <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />
                    Testing…
                  </>
                ) : (
                  <>
                    <PlugIcon className="mr-1.5 h-4 w-4" aria-hidden />
                    Test connection
                  </>
                )}
              </Button>
            )}
          </div>
          <ConnectionLastTestedLine source={source} />
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {/* U14 — Test tab is gated on the lifecycle phase. We can't easily
              wrap a TabsTrigger in a Tooltip without breaking Radix's keyboard
              roving (TabsList expects TabsTrigger as a direct child), so we
              surface the reason via the native `title` attribute when
              disabled. The Sync-tab band and the header Sync-now button still
              get the rich Tooltip treatment. */}
          <TabsTrigger
            value="test"
            disabled={!lifecycle.canChat}
            title={!lifecycle.canChat ? lifecycle.chatReason : undefined}
            data-testid="tab-trigger-test"
          >
            Test
          </TabsTrigger>
          <TabsTrigger value="schema">
            {dataTabLabelFor(source.source_type)}
            {documentsData && sourceKindOf(source.source_type) !== 'database' && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs tabular-nums">
                {documentsData.total}
              </span>
            )}
            {sourceKindOf(source.source_type) === 'database' &&
              source.tables_documented !== null &&
              source.tables_documented !== undefined && (
                <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs tabular-nums">
                  {source.tables_documented}
                </span>
              )}
          </TabsTrigger>
          <TabsTrigger value="sync">Sync</TabsTrigger>
          <TabsTrigger value="access">Access</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        {/* OVERVIEW */}
        <TabsContent value="overview" className="mt-4 space-y-4">
          {/* U14 — lifecycle stepper: surfaces every stage of the pipeline so
              admins see "we're doing something" instead of a quiet "Pending sync"
              pill. The companion progress bar (FX16) renders only while the
              source is in flight; both disappear once ready/failed. */}
          <Card data-testid="overview-lifecycle-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Lifecycle</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <LifecycleStepper phase={lifecycle.phase} />
              <LifecycleProgressBar
                phase={lifecycle.phase}
                detail={
                  source.latest_job?.started_at
                    ? `Started ${formatTimestamp(source.latest_job.started_at)}`
                    : null
                }
              />
              {/* U14 — surface the "Available to users" toggle on Overview
                  too. It's the same component rendered on Settings → both
                  reflect the same `is_active` flag and obey the same gate
                  matrix. */}
              <div className="border-t pt-3">
                <AvailabilityToggle
                  source={source}
                  compact
                  testIdPrefix="overview-availability-toggle"
                />
              </div>
            </CardContent>
          </Card>

          {/* FAILURE CALLOUTS — surface degenerate states above the fold so
              admins entering the page see "what's wrong" before "what's here". */}
          <OverviewCallouts
            source={source}
            isDbSource={isDbSource}
            onRetrySync={() =>
              syncMutation.mutate(id, {
                onSuccess: (job) => {
                  trackSessionJob(job)
                  toast.success('Retry started')
                },
                onError: (err) => toast.error(getErrorMessage(err)),
              })
            }
          />

          {isDbSource ? (
            /* DB sources get the enriched Overview (U10): hero + stat grid
               (Status / Connection / Schema / Access / Retrieval) + "what
               the agent sees" teaser + meta footer. The stat grid embeds
               <StatusCard>; CoverageCard/FreshnessCard are folded in. */
            <DatabaseOverview
              source={source}
              isDbLiveSource={isDbLiveSource}
              onViewSchema={() => setActiveTab('schema')}
              onManageAccess={() => setActiveTab('access')}
              onRestudySchema={() =>
                syncMutation.mutate(id, {
                  onSuccess: (job) => {
                    trackSessionJob(job)
                    toast.success('Re-study started')
                  },
                  onError: (err) => toast.error(getErrorMessage(err)),
                })
              }
            />
          ) : (
            <>
              {/* HEALTH ROW — three source-type-aware status cards replace
                  the old generic Documents/Chunks/Last-synced trio. */}
              <div className="grid gap-4 sm:grid-cols-3">
                <StatusCard source={source} isDbLiveSource={isDbLiveSource} />
                <CoverageCard source={source} isDbSource={isDbSource} stats={stats} />
                <FreshnessCard source={source} isDbSource={isDbSource} />
              </div>

              {/* TYPE-SPECIFIC OVERVIEW BLOCK — the big "what is this source"
                  card adapts to the source type (files / web / connectors). */}
              <SourceTypeOverview source={source} stats={stats} documents={documents} />
            </>
          )}

          {/* AI Description card removed — see AINamingCard on Settings tab.
              The new flow proposes name/description into the form and lets
              the sticky save bar persist, eliminating the dual-writer race. */}
        </TabsContent>

        {/* TEST — admin-only sandbox chat scoped to this source */}
        <TabsContent value="test" className="mt-4">
          <TestTab source={source} />
        </TabsContent>

        {/* DATA — relabeled per source type (Files / Pages / Schema) */}
        <TabsContent value="schema" className="mt-4">
          <DataTabBody
            source={source}
            documents={documents}
            documentsTotal={documentsData?.total ?? documents.length}
          />
        </TabsContent>

        {/* SYNC — density redesign (U1):
            - Inline header band (Sync now + Test connection + last-tested status)
            - Collapsed sync-config metadata strip with Edit-in-Settings link
            - Sync history dominates the tab */}
        <TabsContent value="sync" className="mt-4 space-y-3">
          <SyncHeaderBand
            sourceType={source.source_type}
            sourceName={source.name}
            isDbLiveSource={isDbLiveSource}
            isSyncing={syncMutation.isPending}
            canSyncNow={lifecycle.canSyncNow}
            syncNowReason={lifecycle.syncNowReason}
            onSyncNow={() =>
              syncMutation.mutate(id, {
                onSuccess: (job) => {
                  trackSessionJob(job)
                  toast.success('Sync started')
                  // Reset to first page so the freshly-queued job is visible.
                  setSyncJobsPage(0)
                },
                onError: (err) => toast.error(getErrorMessage(err)),
              })
            }
            isTestingConnection={testConnectionMutation.isPending}
            onTestConnection={() => testConnectionMutation.mutate(id)}
            testConnectionResult={
              testConnectionMutation.isSuccess
                ? {
                    ok: testConnectionMutation.data.success,
                    message: testConnectionMutation.data.message,
                  }
                : testConnectionMutation.isError
                  ? { ok: false, message: getErrorMessage(testConnectionMutation.error) }
                  : null
            }
          />

          <SyncConfigStrip
            source={source}
            onEditInSettings={() => setActiveTab('settings')}
          />

          <SyncHistorySection
            jobs={syncJobs}
            total={syncJobsTotal}
            page={syncJobsPage}
            pageSize={SYNC_JOBS_PAGE_SIZE}
            onPageChange={setSyncJobsPage}
            isDbLiveSource={isDbLiveSource}
          />
        </TabsContent>

        {/* ACCESS */}
        <TabsContent value="access" className="mt-4 space-y-3">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Access control</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Manage which users can query this source. A source with{' '}
                <span className="font-medium">no granted users</span> is
                queryable by no one — even when "Available to users" is on.
              </p>
            </CardHeader>
            <CardContent>
              <PermissionsManager sourceId={id} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* SETTINGS */}
        <TabsContent value="settings" className="mt-4 space-y-4">
          {isDbSource && <ConnectionCard source={source} />}
          <EditableSettingsForm source={source} />

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Visibility</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Type</span>
                <Badge variant="secondary">{source.source_type}</Badge>
              </div>
              {/* U14 — shared availability toggle. The same component renders
                  on the Overview tab; both stay in sync because they read off
                  the same React Query cache. PRD §11 naming/description
                  blockers + the lifecycle phase gate are folded into
                  `AvailabilityToggle` so there's only one place that decides
                  approvability. */}
              <AvailabilityToggle
                source={source}
                testIdPrefix="settings-availability-toggle"
              />
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Citations enabled</span>
                <Switch
                  checked={source.citations_enabled}
                  disabled={updateMutation.isPending}
                  onCheckedChange={(checked) =>
                    updateMutation.mutate(
                      { citations_enabled: checked },
                      {
                        onSuccess: () => toast.success('Citations setting updated'),
                        onError: (err) => toast.error(getErrorMessage(err)),
                      }
                    )
                  }
                  aria-label="Toggle citations"
                />
              </div>
            </CardContent>
          </Card>

          <div className="rounded-md border border-destructive/40 p-4">
            <h3 className="text-sm font-medium text-destructive">Danger zone</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Deleting a source permanently removes all indexed documents and cannot be undone.
            </p>
            <Button
              className="mt-3"
              variant="destructive"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2Icon className="mr-1.5 h-4 w-4" />
              Delete source
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {/* Delete confirmation */}
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{source.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the source and all indexed documents.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteMutation.isPending}
              onClick={() =>
                deleteMutation.mutate(id, {
                  onSuccess: () => {
                    toast.success('Source deleted')
                    router.push('/admin/sources')
                  },
                  onError: (err) => toast.error(getErrorMessage(err)),
                })
              }
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page header — "Last tested …" persistent line
// ---------------------------------------------------------------------------

interface ConnectionLastTestedLineProps {
  source: SourceDetail
}

/**
 * Persistent "last tested" indicator below the page header.
 *
 * Reads `connection_last_checked_at` and `connection_last_error` (Slice A).
 * Renders nothing for source types that don't expose a connection probe
 * (e.g. file_upload — there's nothing remote to test).
 *
 * Both `connection_last_checked_at` and `connection_last_error` are
 * optional on the wire — when absent we hide the line entirely rather
 * than print "Last tested never" which adds noise without information.
 */
function ConnectionLastTestedLine({ source }: ConnectionLastTestedLineProps) {
  if (!isConnectionTestable(source.source_type)) return null
  const checkedAt = source.connection_last_checked_at
  if (!checkedAt) return null
  const succeeded = !source.connection_last_error
  const tone = succeeded
    ? 'text-emerald-700 dark:text-emerald-400'
    : 'text-destructive'
  return (
    <p
      className={cn('text-xs', tone)}
      data-testid="header-connection-last-tested"
      role="status"
    >
      Last tested {formatTimestamp(checkedAt)} —{' '}
      {succeeded ? 'succeeded' : `failed: ${source.connection_last_error}`}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Sync tab — inline header band (replaces the standalone Actions Card)
//
// Density redesign (U1): a single-row band with Sync now + Test connection +
// inline status text. ~44px tall. NO CardHeader/CardContent chrome.
// ---------------------------------------------------------------------------

interface SyncHeaderBandProps {
  sourceType: SourceType
  sourceName: string
  isSyncing: boolean
  onSyncNow: () => void
  isTestingConnection: boolean
  onTestConnection: () => void
  testConnectionResult: { ok: boolean; message: string } | null
  /** When true, the source uses live retrieval (text_to_query) — relabel
   *  "Sync now" to "Re-study schema" because there are no documents to sync. */
  isDbLiveSource?: boolean
  /** Lifecycle gate — disable the primary button when the source is mid-
   *  ingestion. Defaults to `true` for callers that haven't migrated. */
  canSyncNow?: boolean
  /** Reason the gate is closed; rendered as a tooltip. */
  syncNowReason?: string
}

function SyncHeaderBand({
  sourceType,
  sourceName,
  isSyncing,
  onSyncNow,
  isTestingConnection,
  onTestConnection,
  testConnectionResult,
  isDbLiveSource,
  canSyncNow = true,
  syncNowReason = '',
}: SyncHeaderBandProps) {
  const showTestConnection = isConnectionTestable(sourceType)
  const primaryLabel = isDbLiveSource ? 'Re-study schema' : 'Sync now'
  const primaryActiveLabel = isDbLiveSource ? 'Studying…' : 'Starting…'

  const syncButton = (
    <Button
      variant="default"
      size="sm"
      onClick={onSyncNow}
      disabled={isSyncing || !canSyncNow}
      className="w-full sm:w-auto"
      aria-label={
        isDbLiveSource
          ? `Re-study schema for ${sourceName}`
          : `Sync source ${sourceName} now`
      }
    >
      {isSyncing ? (
        <>
          <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />
          {primaryActiveLabel}
        </>
      ) : (
        <>
          <RefreshCwIcon className="mr-1.5 h-4 w-4" aria-hidden />
          {primaryLabel}
        </>
      )}
    </Button>
  )

  return (
    <div
      data-testid="sync-header-band"
      className="flex flex-col gap-2 rounded-md border bg-card px-3 py-2 sm:flex-row sm:items-center sm:gap-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        {!canSyncNow && syncNowReason ? (
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="contents">{syncButton}</span>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-[260px] text-xs">
                {syncNowReason}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          syncButton
        )}

        {showTestConnection && (
          <Button
            variant="outline"
            size="sm"
            onClick={onTestConnection}
            disabled={isTestingConnection}
            className="w-full sm:w-auto"
            aria-label="Test connection"
          >
            {isTestingConnection ? (
              <>
                <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />
                Testing…
              </>
            ) : (
              <>
                <PlugIcon className="mr-1.5 h-4 w-4" aria-hidden />
                Test connection
              </>
            )}
          </Button>
        )}
      </div>

      {showTestConnection && testConnectionResult !== null && (
        <div
          data-testid="test-connection-result"
          role={testConnectionResult.ok ? 'status' : 'alert'}
          aria-live="polite"
          className={cn(
            'flex items-start gap-1.5 rounded px-2 py-1 text-xs sm:ml-auto',
            testConnectionResult.ok
              ? 'text-emerald-700 dark:text-emerald-300'
              : 'text-destructive'
          )}
        >
          {testConnectionResult.ok ? (
            <CheckCircle2Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            <XCircleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          )}
          <span>
            {testConnectionResult.message ||
              (testConnectionResult.ok ? 'Connection succeeded' : 'Connection failed')}
          </span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sync tab — collapsed config metadata strip
//
// Density redesign (U1): single-row "Mode: Manual · Source mode: Snapshot ·
// Schedule: 0 2 * * *" with a chevron disclosure. Read-only chips when
// expanded; the "Edit in Settings" link switches the active tab so the
// admin can change values via the existing form.
// ---------------------------------------------------------------------------

interface SyncConfigStripProps {
  source: SourceDetail
  onEditInSettings: () => void
}

function SyncConfigStrip({ source, onEditInSettings }: SyncConfigStripProps) {
  // Default-collapsed on mobile is a CSS-only concern — there's no `expanded`
  // server state to remember. Default to collapsed everywhere so the history
  // table dominates the tab.
  const [expanded, setExpanded] = useState(false)

  const summary: string = [
    `Mode: ${SYNC_MODE_LABELS[source.sync_mode]}`,
    `Source mode: ${SOURCE_MODE_LABELS[source.source_mode]}`,
    source.sync_schedule ? `Schedule: ${source.sync_schedule}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div
      data-testid="sync-config-strip"
      data-expanded={expanded}
      className="rounded-md border bg-card"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs"
        aria-expanded={expanded}
        aria-controls="sync-config-strip-body"
        data-testid="sync-config-strip-toggle"
      >
        <span className="truncate text-muted-foreground">{summary}</span>
        <ChevronDownIcon
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-180'
          )}
          aria-hidden
        />
      </button>
      {expanded && (
        <div
          id="sync-config-strip-body"
          className="space-y-2 border-t px-3 py-3 text-sm"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Mode</span>
              <SyncModeBadge mode={source.sync_mode} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Source mode</span>
              <SourceModeBadge mode={source.source_mode} />
            </div>
            {source.sync_schedule && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Schedule</span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                  {source.sync_schedule}
                </code>
              </div>
            )}
          </div>
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={onEditInSettings}
            className="h-auto p-0 text-xs"
            data-testid="sync-config-edit-in-settings"
          >
            Edit in Settings →
          </Button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sync tab — paginated history (density redesign)
// ---------------------------------------------------------------------------

interface SyncHistorySectionProps {
  jobs: ReadonlyArray<{
    id: string
    status: string
    documents_indexed: number
    error_message: string | null
    started_at: string | null
  }>
  total: number
  page: number
  pageSize: number
  onPageChange: (next: number) => void
  /** When true, relabel "Sync history" → "Study runs". DB live sources
   *  don't ingest documents; what the worker records is a study run. */
  isDbLiveSource?: boolean
}

function SyncHistorySection({
  jobs,
  total,
  page,
  pageSize,
  onPageChange,
  isDbLiveSource,
}: SyncHistorySectionProps) {
  const offset = page * pageSize
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + jobs.length, total)
  const isFirstPage = page === 0
  const isLastPage = (page + 1) * pageSize >= total
  const showFooter = total > 0 && total > pageSize
  const sectionTitle = isDbLiveSource ? 'Study runs' : 'Sync history'
  const emptyCopy = isDbLiveSource
    ? 'No study runs yet. Click Re-study schema to start one.'
    : 'No sync runs yet.'

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{sectionTitle}</h3>
        {/* Counter moves into the header (density redesign U1). */}
        {total > 0 && (
          <span
            className="text-xs text-muted-foreground"
            data-testid="sync-jobs-page-summary"
          >
            Showing {start}–{end} of {total}
          </span>
        )}
      </div>
      {total === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">{emptyCopy}</p>
      ) : (
        <div className="rounded-md border">
          <div className="divide-y">
            {jobs.map((job) => (
              <div
                /* Tightened from py-3 → py-2.5 so 15 rows fit at 1080p (was 10). */
                className="flex flex-col gap-1 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-4"
                key={job.id}
                data-testid="sync-jobs-row"
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={job.status} />
                    {job.documents_indexed > 0 && (
                      <span className="text-xs text-muted-foreground">
                        {job.documents_indexed} docs indexed
                      </span>
                    )}
                  </div>
                  {job.error_message && (
                    <p className="break-words text-xs text-destructive">{job.error_message}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatTimestamp(job.started_at)}
                </span>
              </div>
            ))}
          </div>
          {showFooter && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t px-3 py-2 text-xs text-muted-foreground sm:px-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(page - 1)}
                disabled={isFirstPage}
                aria-label="Previous page of sync history"
                data-testid="sync-jobs-prev"
              >
                <ChevronLeftIcon className="mr-1 h-3.5 w-3.5" aria-hidden />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(page + 1)}
                disabled={isLastPage}
                aria-label="Next page of sync history"
                data-testid="sync-jobs-next"
              >
                Next
                <ChevronRightIcon className="ml-1 h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings tab — editable form (now also hosts the AI naming card)
// ---------------------------------------------------------------------------

interface EditableSettingsFormProps {
  source: SourceDetail
}

function EditableSettingsForm({ source }: EditableSettingsFormProps) {
  const updateMutation = useUpdateSource(source.id)
  const defaultValues = useMemo(() => sourceToFormValues(source), [source])

  const form = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
    defaultValues,
  })

  // The detail page stays mounted across saves; React Query updates `source`
  // in place after a successful PATCH. Reset the form so the new server state
  // becomes the new pristine baseline (otherwise saved fields stay marked
  // dirty and the Save bar lingers).
  useEffect(() => {
    form.reset(defaultValues)
  }, [defaultValues, form])

  const isDirty = form.formState.isDirty
  const dirtyFieldCount = Object.keys(form.formState.dirtyFields).length
  const syncMode = form.watch('sync_mode')
  const currentSourceMode = form.watch('source_mode')
  const isPendingName = source.name_status === 'pending_ai'

  // Per-source-type form gating. Recomputed on `source_mode` change because
  // a DB source flips its sync_mode visibility when toggled snapshot⇄live.
  const fieldConfig: FormFieldConfig = useMemo(
    () => getEditableFieldsFor({ sourceType: source.source_type, sourceMode: currentSourceMode }),
    [source.source_type, currentSourceMode]
  )

  const onSubmit = form.handleSubmit((values) => {
    const patch = diffSourceUpdate(source, values)
    if (Object.keys(patch).length === 0) {
      // Defensive: if Save fires with no diff, just clear the dirty flag.
      form.reset(values)
      return
    }
    updateMutation.mutate(patch, {
      onSuccess: (updated) => {
        toast.success('Source updated')
        // Re-baseline against the server response so editor state matches
        // canonical values (handles any server-side normalization).
        form.reset(sourceToFormValues(updated))
      },
      onError: (err) => toast.error(getErrorMessage(err)),
    })
  })

  function onDiscard() {
    form.reset(defaultValues)
  }

  // AI naming proposal accepted → fill the form fields. shouldDirty:true so
  // the sticky save bar lights up. `shouldValidate:true` runs the schema
  // immediately so the user sees inline errors before they click Save.
  function applyAiProposal(proposed: { name?: string; description: string }) {
    if (typeof proposed.name === 'string') {
      form.setValue('name', proposed.name, {
        shouldDirty: true,
        shouldValidate: true,
        shouldTouch: true,
      })
    }
    form.setValue('description', proposed.description, {
      shouldDirty: true,
      shouldValidate: true,
      shouldTouch: true,
    })
  }

  return (
    <>
      {/* AI naming assistant lives ABOVE the form (U3). It calls the form's
          setValue via the onApply callback, so the sticky save bar updates
          instead of writing directly. */}
      <AINamingCard source={source} onApply={applyAiProposal} />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Source settings</CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={onSubmit} className="space-y-4" aria-label="Edit source settings">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    {isPendingName && (
                      <p className="text-xs text-muted-foreground" data-testid="naming-hint">
                        Naming… the assistant is still drafting a name. Typing here will replace its
                        draft.
                      </p>
                    )}
                    <FormControl>
                      <Input
                        placeholder="My Knowledge Base"
                        maxLength={255}
                        autoComplete="off"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="What documents does this source contain?"
                        maxLength={2000}
                        rows={3}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Up to 2000 characters. Used to help users find this source in the picker.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Retrieval mode + Source mode — gated by source type. DB sources
                  show read-only chips with a tooltip explaining why; files /
                  web / connectors hide the field entirely (vector_only is the
                  only sensible value, set at creation). */}
              {(fieldConfig.retrievalMode !== 'hidden' ||
                fieldConfig.sourceMode !== 'hidden') && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {fieldConfig.retrievalMode === 'edit' ? (
                    <FormField
                      control={form.control}
                      name="retrieval_mode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Retrieval mode</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {RETRIEVAL_MODES_EDITABLE.map((mode) => (
                                <SelectItem key={mode} value={mode}>
                                  {RETRIEVAL_MODE_LABELS[mode]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : fieldConfig.retrievalMode === 'readonly-chip' ? (
                    <ReadonlyFieldChip
                      label="Retrieval mode"
                      value={RETRIEVAL_MODE_LABELS[source.retrieval_mode]}
                      tooltip="Database sources answer queries by translating natural language to SQL — vector retrieval doesn't apply."
                      testId="retrieval-mode-chip"
                    />
                  ) : null}

                  {fieldConfig.sourceMode === 'edit' ? (
                    <FormField
                      control={form.control}
                      name="source_mode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Source mode</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {SOURCE_MODES.map((mode) => (
                                <SelectItem key={mode} value={mode}>
                                  {SOURCE_MODE_LABELS[mode]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : fieldConfig.sourceMode === 'readonly-chip' ? (
                    <ReadonlyFieldChip
                      label="Source mode"
                      value={SOURCE_MODE_LABELS[source.source_mode]}
                      tooltip="Database sources query the live database at retrieval time — they don't snapshot rows into the index."
                      testId="source-mode-chip"
                    />
                  ) : null}
                </div>
              )}

              {fieldConfig.syncModeOptions.length > 0 ? (
                <FormField
                  control={form.control}
                  name="sync_mode"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Sync mode</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {fieldConfig.syncModeOptions.map((mode) => (
                            <SelectItem key={mode} value={mode}>
                              {SYNC_MODE_LABELS[mode]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ) : null}

              {syncMode === 'scheduled' && fieldConfig.syncModeOptions.includes('scheduled') && (
                <FormField
                  control={form.control}
                  name="sync_schedule"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Cron schedule</FormLabel>
                      <FormControl>
                        <Input placeholder="0 2 * * *" autoComplete="off" {...field} />
                      </FormControl>
                      <FormDescription>
                        Cron expression (UTC). Example: <code>0 2 * * *</code> = daily at 02:00 UTC.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              <SettingsSaveBar
                isDirty={isDirty}
                dirtyFieldCount={dirtyFieldCount}
                isSaving={updateMutation.isPending}
                onDiscard={onDiscard}
              />
            </form>
          </Form>
        </CardContent>
      </Card>
    </>
  )
}

// ---------------------------------------------------------------------------
// Sticky always-visible save bar
// ---------------------------------------------------------------------------

interface SettingsSaveBarProps {
  isDirty: boolean
  dirtyFieldCount: number
  isSaving: boolean
  onDiscard: () => void
}

/**
 * Always-rendered footer at the bottom of the Settings card. The previous
 * implementation revealed itself only when the form was dirty — that read as
 * "where did the Save button go?" to admins on first load. Always rendering
 * (with Save disabled until dirty) keeps the affordance discoverable while
 * still preventing no-op submits.
 */
function SettingsSaveBar({
  isDirty,
  dirtyFieldCount,
  isSaving,
  onDiscard,
}: SettingsSaveBarProps) {
  const dotClass = isDirty ? 'bg-primary' : 'bg-muted-foreground/40'
  const summary = isDirty
    ? `${dirtyFieldCount} unsaved change${dirtyFieldCount === 1 ? '' : 's'}`
    : 'No unsaved changes'
  return (
    <div
      className="sticky bottom-0 -mx-6 -mb-6 mt-4 flex items-center justify-between gap-3 border-t bg-card/95 px-6 py-3 backdrop-blur"
      data-testid="settings-save-bar"
      data-dirty={isDirty}
    >
      <div className="flex items-center gap-2 text-sm">
        <span
          className={cn('inline-block h-2 w-2 rounded-full', dotClass)}
          aria-hidden
          data-testid="settings-save-bar-dot"
        />
        <span className="text-muted-foreground" data-testid="settings-save-bar-summary">
          {summary}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDiscard}
          disabled={!isDirty || isSaving}
          data-testid="settings-discard"
        >
          Discard
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={!isDirty || isSaving}
          data-testid="settings-save"
        >
          {isSaving ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Read-only chip for locked-by-source-type fields
// ---------------------------------------------------------------------------

interface ReadonlyFieldChipProps {
  label: string
  value: string
  tooltip: string
  testId?: string
}

/**
 * Renders a label + Badge pair that visually parallels a Select field but
 * is non-interactive. Used to show DB sources their locked
 * `retrieval_mode` / `source_mode` values without putting an editable
 * Select on screen that would mis-suggest the values are user-mutable.
 */
function ReadonlyFieldChip({ label, value, tooltip, testId }: ReadonlyFieldChipProps) {
  return (
    <div className="space-y-2" data-testid={testId}>
      <p className="text-sm font-medium">{label}</p>
      <TooltipProvider delayDuration={250}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Badge variant="secondary" className="cursor-help">
                <LockIcon className="mr-1.5 h-3 w-3" aria-hidden />
                {value}
              </Badge>
            </span>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-[260px]">
            {tooltip}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Data tab body — per-type relabeled list
// ---------------------------------------------------------------------------

interface DataTabBodyProps {
  source: SourceDetail
  documents: ReadonlyArray<{ id: string; created_at: string; is_active: boolean }>
  documentsTotal: number
}

/**
 * Renders the second-tab body. The label-and-noun decisions live in
 * `sourceTypeMatrix.ts`; this component just wires them in. Database
 * sources show a placeholder until per-table data lands on the wire — the
 * studying agent's `tables_documented` count is the only DB-specific field
 * we have today.
 */
function DataTabBody({ source, documents, documentsTotal }: DataTabBodyProps) {
  const kind = sourceKindOf(source.source_type)
  const idLabel =
    kind === 'database' ? 'Table' : kind === 'file' ? 'File ID' : 'Page ID'

  if (kind === 'database') {
    return <SchemaViewer sourceId={source.id} source={source} />
  }

  if (documents.length === 0) {
    return (
      <p
        className="py-8 text-center text-sm text-muted-foreground"
        data-testid="data-tab-empty"
      >
        {emptyDataCopyFor(source.source_type)}
      </p>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border" data-testid="data-tab-list">
      <Table className="min-w-[560px]">
        <TableHeader>
          <TableRow>
            <TableHead>{idLabel}</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Indexed at</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents.map((doc) => (
            <TableRow key={doc.id}>
              <TableCell
                className="max-w-[180px] truncate font-mono text-xs text-muted-foreground"
                title={doc.id}
              >
                {doc.id}
              </TableCell>
              <TableCell>
                <Badge variant={doc.is_active ? 'default' : 'secondary'}>
                  {doc.is_active ? 'active' : 'inactive'}
                </Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatTimestamp(doc.created_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {documentsTotal > documents.length && (
        <div className="border-t px-4 py-2 text-xs text-muted-foreground">
          Showing {documents.length} of {documentsTotal} {dataNounFor(source.source_type)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings tab — Connection card (U8)
//
// DB-only Settings card that surfaces connection health at a glance and
// hosts the "Edit credentials" affordance. The dialog itself
// (`EditCredentialsDialog`) handles the form, the FX4 re-auth gate, and
// the test-then-persist flow on the backend.
//
// We deliberately avoid rendering the connection_uri / host here — the
// detail endpoint never returns them (FR-020 forbids exposing the
// decrypted config), so we render a status-summary instead and trust the
// admin to know what they typed.
// ---------------------------------------------------------------------------

interface ConnectionCardProps {
  source: SourceDetail
}

function ConnectionCard({ source }: ConnectionCardProps) {
  const [editOpen, setEditOpen] = useState(false)

  const checkedAt = source.connection_last_checked_at
  const succeeded = !source.connection_last_error
  const checkedLine = checkedAt
    ? `Last checked ${formatTimestamp(checkedAt)} — ${
        succeeded ? 'succeeded' : `failed: ${source.connection_last_error}`
      }`
    : 'No connection check has been recorded yet.'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Connection</CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Database connection details are encrypted at rest and never
          displayed back. Use Edit credentials to rotate them.
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">Status</span>
          <Badge
            variant={
              source.connection_status === 'healthy'
                ? 'default'
                : source.connection_status === 'failed'
                  ? 'destructive'
                  : 'secondary'
            }
            data-testid="connection-card-status"
          >
            {source.connection_status ?? 'unknown'}
          </Badge>
        </div>
        <p
          className={cn(
            'text-xs',
            checkedAt && !succeeded
              ? 'text-destructive'
              : 'text-muted-foreground'
          )}
          data-testid="connection-card-last-checked"
        >
          {checkedLine}
        </p>
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setEditOpen(true)}
            data-testid="connection-card-edit"
          >
            Edit credentials
          </Button>
        </div>
      </CardContent>

      <EditCredentialsDialog
        source={source}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
    </Card>
  )
}
