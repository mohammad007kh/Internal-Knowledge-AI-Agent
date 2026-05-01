'use client'

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
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ErrorState } from '@/components/ui/ErrorState'
import {
  SourceModeBadge,
  StatusBadge,
  SyncModeBadge,
  formatTimestamp,
} from '@/features/sources/source-ui'
import {
  useDeleteSource,
  useRefreshDescription,
  useSource,
  useSourceDocuments,
  useSourceStats,
  useSyncJobs,
  useTriggerSync,
  useUpdateSource,
} from '@/features/sources/hooks/useSources'
import { getErrorMessage } from '@/lib/errors'
import { ChevronRightIcon, RefreshCwIcon, Trash2Icon } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

export default function SourceDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const { data: source, isLoading, isError, error, refetch } = useSource(id)
  const { data: stats } = useSourceStats(id)
  const { data: syncJobsData } = useSyncJobs(id)
  const { data: documentsData } = useSourceDocuments(id)

  const syncMutation = useTriggerSync()
  const deleteMutation = useDeleteSource()
  const updateMutation = useUpdateSource(id)
  const refreshDesc = useRefreshDescription(id)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [proposedDesc, setProposedDesc] = useState<string | null>(null)

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
  const documents = documentsData?.items ?? []

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link href="/admin/sources" className="hover:text-foreground hover:underline">
          Sources
        </Link>
        <ChevronRightIcon className="h-4 w-4" aria-hidden />
        <span className="font-medium text-foreground">{source.name}</span>
      </nav>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="break-words text-xl font-bold md:text-2xl">{source.name}</h1>
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
                <CardTitle className="text-sm font-medium text-muted-foreground">Documents</CardTitle>
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
                <CardTitle className="text-sm font-medium text-muted-foreground">Last synced</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{formatTimestamp(source.last_synced_at)}</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">AI Description</CardTitle>
              <Button
                variant="outline"
                size="sm"
                disabled={refreshDesc.isPending}
                onClick={() =>
                  refreshDesc.mutate(undefined, {
                    onSuccess: (data) => setProposedDesc(data.proposed_description),
                    onError: (err) => toast.error(getErrorMessage(err)),
                  })
                }
              >
                {refreshDesc.isPending ? 'Generating…' : 'Refresh'}
              </Button>
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
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{source.sync_schedule}</code>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Source mode</span>
                <SourceModeBadge mode={source.source_mode} />
              </div>
            </CardContent>
          </Card>

          <div>
            <h3 className="mb-3 text-sm font-medium">Sync history</h3>
            {syncJobs.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">No sync runs yet.</p>
            ) : (
              <div className="divide-y rounded-md border">
                {syncJobs.map((job) => (
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
            )}
          </div>
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
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Source settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Type</span>
                <Badge variant="secondary">{source.source_type}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Retrieval mode</span>
                <Badge variant="secondary">{source.retrieval_mode.replace(/_/g, ' ')}</Badge>
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

      {/* Proposed description dialog */}
      <Dialog open={!!proposedDesc} onOpenChange={(o) => !o && setProposedDesc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Proposed description</DialogTitle>
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
