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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { Textarea } from '@/components/ui/textarea'
import {
  useDeleteSource,
  useAutoNameSource,
  useRefreshDescription,
  useSource,
  useSourceDocuments,
  useSourceStats,
  useSyncJobs,
  useTestConnection,
  useTriggerSync,
  useUpdateSource,
} from '@/features/sources/hooks/useSources'
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
  SyncMode,
  UpdateSourceRequest,
} from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  CheckCircle2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Loader2Icon,
  PlugIcon,
  RefreshCwIcon,
  Trash2Icon,
  XCircleIcon,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

// ---------------------------------------------------------------------------
// Pagination + form constants
// ---------------------------------------------------------------------------

const SYNC_JOBS_PAGE_SIZE = 20

const RETRIEVAL_MODES: readonly RetrievalMode[] = ['vector_only', 'text_to_query', 'hybrid']
const SYNC_MODES: readonly SyncMode[] = ['manual', 'scheduled', 'delta']
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

  const { data: source, isLoading, isError, error, refetch } = useSource(id)
  const { data: stats } = useSourceStats(id)
  const { data: syncJobsData } = useSyncJobs(id, {
    limit: SYNC_JOBS_PAGE_SIZE,
    offset: syncJobsPage * SYNC_JOBS_PAGE_SIZE,
  })
  const { data: documentsData } = useSourceDocuments(id)

  const syncMutation = useTriggerSync()
  const testConnectionMutation = useTestConnection()
  const deleteMutation = useDeleteSource()
  const updateMutation = useUpdateSource(id)
  const refreshDesc = useRefreshDescription(id)
  const autoName = useAutoNameSource(id)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [proposedDesc, setProposedDesc] = useState<string | null>(null)
  // Holds the AI's proposed { name, description } pair from the Regenerate
  // button. Distinct from `proposedDesc` (which is a single string from the
  // legacy refresh-description flow) because Regenerate proposes BOTH and
  // the admin gets to confirm both at once.
  const [proposedAutoName, setProposedAutoName] = useState<
    { name: string; description: string } | null
  >(null)

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
          </div>
          {source.description && (
            <p className="text-sm text-muted-foreground">{source.description}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={source.status} />
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              syncMutation.mutate(id, {
                onSuccess: () => toast.success('Sync started'),
                onError: (err) => toast.error(getErrorMessage(err)),
              })
            }
            disabled={syncMutation.isPending}
            aria-label={`Sync source ${source.name}`}
          >
            <RefreshCwIcon className="mr-1.5 h-4 w-4" />
            Sync now
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="documents">
            Documents
            {documentsData && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs tabular-nums">
                {documentsData.total}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="sync">Sync</TabsTrigger>
          <TabsTrigger value="access">Access</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        {/* OVERVIEW */}
        <TabsContent value="overview" className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Documents
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold tabular-nums">{stats?.document_count ?? '—'}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Chunks</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold tabular-nums">{stats?.chunk_count ?? '—'}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Last synced
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{formatTimestamp(source.last_synced_at)}</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
              <CardTitle className="text-sm font-medium">AI Description</CardTitle>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={refreshDesc.isPending || autoName.isPending}
                  onClick={() =>
                    refreshDesc.mutate(undefined, {
                      onSuccess: (data) => setProposedDesc(data.proposed_description),
                      onError: (err) => toast.error(getErrorMessage(err)),
                    })
                  }
                >
                  {refreshDesc.isPending ? 'Generating…' : 'Refresh description'}
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  disabled={autoName.isPending || refreshDesc.isPending}
                  onClick={() =>
                    autoName.mutate(undefined, {
                      onSuccess: (data) =>
                        setProposedAutoName({
                          name: data.proposed_name,
                          description: data.proposed_description,
                        }),
                      onError: (err) => toast.error(getErrorMessage(err)),
                    })
                  }
                >
                  {autoName.isPending ? 'Regenerating…' : 'Regenerate name + description'}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                {source.description || 'No description yet. Click Refresh to generate one.'}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* DOCUMENTS */}
        <TabsContent value="documents" className="mt-4">
          {documents.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No documents indexed yet. Run a sync to populate this source.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table className="min-w-[560px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Document ID</TableHead>
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
              {documentsData && documentsData.total > documents.length && (
                <div className="border-t px-4 py-2 text-xs text-muted-foreground">
                  Showing {documents.length} of {documentsData.total} documents
                </div>
              )}
            </div>
          )}
        </TabsContent>

        {/* SYNC */}
        <TabsContent value="sync" className="mt-4 space-y-4">
          <SyncActions
            sourceType={source.source_type}
            sourceName={source.name}
            isSyncing={syncMutation.isPending}
            onSyncNow={() =>
              syncMutation.mutate(id, {
                onSuccess: () => {
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
                ? { ok: testConnectionMutation.data.success, message: testConnectionMutation.data.message }
                : testConnectionMutation.isError
                  ? { ok: false, message: getErrorMessage(testConnectionMutation.error) }
                  : null
            }
          />

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Sync configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Mode</span>
                <SyncModeBadge mode={source.sync_mode} />
              </div>
              {source.sync_schedule && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Schedule</span>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                    {source.sync_schedule}
                  </code>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Source mode</span>
                <SourceModeBadge mode={source.source_mode} />
              </div>
            </CardContent>
          </Card>

          <SyncHistorySection
            jobs={syncJobs}
            total={syncJobsTotal}
            page={syncJobsPage}
            pageSize={SYNC_JOBS_PAGE_SIZE}
            onPageChange={setSyncJobsPage}
          />
        </TabsContent>

        {/* ACCESS */}
        <TabsContent value="access" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Access control</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Manage which users can query this source in{' '}
                <Link
                  href={`/admin/sources/${id}/permissions`}
                  className="underline hover:text-foreground"
                >
                  Permissions settings
                </Link>
                .
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* SETTINGS */}
        <TabsContent value="settings" className="mt-4 space-y-4">
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
              <div className="flex items-center justify-between">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <span className="block text-muted-foreground">Available to users</span>
                  <span className="block text-xs text-muted-foreground/80">
                    When off, the source is hidden from the chat session source picker. New sources
                    start off until approved by an admin.
                  </span>
                </div>
                <Switch
                  checked={source.is_active}
                  disabled={updateMutation.isPending}
                  onCheckedChange={(checked) =>
                    updateMutation.mutate(
                      { is_active: checked },
                      {
                        onSuccess: () =>
                          toast.success(
                            checked
                              ? 'Source approved — now available to users'
                              : 'Source hidden from users'
                          ),
                        onError: (err) => toast.error(getErrorMessage(err)),
                      }
                    )
                  }
                  aria-label="Toggle source availability to users"
                />
              </div>
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

      {/* Proposed name+description dialog (Regenerate flow). Confirms BOTH at
          once, distinguishing the AI-name update from a description-only
          refresh. Persists via the same updateMutation. */}
      <Dialog
        open={!!proposedAutoName}
        onOpenChange={(o) => !o && setProposedAutoName(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Proposed name + description</DialogTitle>
            <DialogDescription>
              The assistant read this source and drafted a clear name and
              retrieval-friendly description. Review both, then save to replace
              the current values.
            </DialogDescription>
          </DialogHeader>
          {proposedAutoName ? (
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Name
                </p>
                <p className="font-medium">{proposedAutoName.name}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Description
                </p>
                <p>{proposedAutoName.description}</p>
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setProposedAutoName(null)}>
              Discard
            </Button>
            <Button
              disabled={updateMutation.isPending || !proposedAutoName}
              onClick={() => {
                if (!proposedAutoName) return
                updateMutation.mutate(
                  {
                    name: proposedAutoName.name,
                    description: proposedAutoName.description,
                  },
                  {
                    onSuccess: () => {
                      toast.success('Name + description updated')
                      setProposedAutoName(null)
                    },
                    onError: (err) => toast.error(getErrorMessage(err)),
                  }
                )
              }}
            >
              {updateMutation.isPending ? 'Saving…' : 'Save both'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Proposed description dialog */}
      <Dialog open={!!proposedDesc} onOpenChange={(o) => !o && setProposedDesc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Proposed description</DialogTitle>
            <DialogDescription>
              AI-generated draft. Review the text below and save it to replace the source's current
              description.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">{proposedDesc}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProposedDesc(null)}>
              Discard
            </Button>
            <Button
              disabled={updateMutation.isPending}
              onClick={() =>
                updateMutation.mutate(
                  { description: proposedDesc ?? undefined },
                  {
                    onSuccess: () => {
                      toast.success('Description updated')
                      setProposedDesc(null)
                    },
                    onError: (err) => toast.error(getErrorMessage(err)),
                  }
                )
              }
            >
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
// Sync tab — action buttons (Sync now + Test connection)
// ---------------------------------------------------------------------------

interface SyncActionsProps {
  sourceType: SourceType
  sourceName: string
  isSyncing: boolean
  onSyncNow: () => void
  isTestingConnection: boolean
  onTestConnection: () => void
  testConnectionResult: { ok: boolean; message: string } | null
}

function SyncActions({
  sourceType,
  sourceName,
  isSyncing,
  onSyncNow,
  isTestingConnection,
  onTestConnection,
  testConnectionResult,
}: SyncActionsProps) {
  const showTestConnection = isConnectionTestable(sourceType)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="default"
            size="sm"
            onClick={onSyncNow}
            disabled={isSyncing}
            aria-label={`Sync source ${sourceName} now`}
          >
            {isSyncing ? (
              <>
                <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />
                Starting…
              </>
            ) : (
              <>
                <RefreshCwIcon className="mr-1.5 h-4 w-4" aria-hidden />
                Sync now
              </>
            )}
          </Button>

          {showTestConnection && (
            <Button
              variant="outline"
              size="sm"
              onClick={onTestConnection}
              disabled={isTestingConnection}
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
            className={
              testConnectionResult.ok
                ? 'flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300'
                : 'flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive'
            }
          >
            {testConnectionResult.ok ? (
              <CheckCircle2Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            ) : (
              <XCircleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            )}
            <span>
              {testConnectionResult.message || (testConnectionResult.ok ? 'Connection succeeded' : 'Connection failed')}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Sync tab — paginated history
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
}

function SyncHistorySection({ jobs, total, page, pageSize, onPageChange }: SyncHistorySectionProps) {
  const offset = page * pageSize
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + jobs.length, total)
  const isFirstPage = page === 0
  const isLastPage = (page + 1) * pageSize >= total
  const showFooter = total > 0 && total > pageSize

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium">Sync history</h3>
      {total === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">No sync runs yet.</p>
      ) : (
        <div className="rounded-md border">
          <div className="divide-y">
            {jobs.map((job) => (
              <div
                className="flex flex-col gap-1 px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-4"
                key={job.id}
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
            <div className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2 text-xs text-muted-foreground sm:px-4">
              <span data-testid="sync-jobs-page-summary">
                Showing {start}–{end} of {total}
              </span>
              <div className="flex items-center gap-2">
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
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings tab — editable form
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
  const syncMode = form.watch('sync_mode')
  const isPendingName = source.name_status === 'pending_ai'

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

  return (
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

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                        {RETRIEVAL_MODES.map((mode) => (
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
            </div>

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
                      {SYNC_MODES.map((mode) => (
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

            {syncMode === 'scheduled' && (
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

            {isDirty && (
              <div className="flex items-center gap-3 border-t pt-4">
                <Button
                  type="submit"
                  size="sm"
                  disabled={updateMutation.isPending}
                  data-testid="settings-save"
                >
                  {updateMutation.isPending ? 'Saving…' : 'Save changes'}
                </Button>
                <button
                  type="button"
                  onClick={onDiscard}
                  className="text-sm text-muted-foreground underline-offset-4 hover:underline"
                  data-testid="settings-discard"
                >
                  Discard
                </button>
              </div>
            )}
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}
