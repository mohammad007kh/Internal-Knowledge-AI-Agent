'use client'

import { SourceRowCard } from '@/app/(admin)/admin/sources/_components/SourceRowCard'
import {
  SourcesToolbar,
  type StatusFilter,
  type TypeGroup,
} from '@/app/(admin)/admin/sources/_components/SourcesToolbar'
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
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatRelative } from '@/features/sources/format'
import {
  useDeleteSource,
  useListSources,
  useTriggerSync,
} from '@/features/sources/hooks/useSources'
import { SourceModeBadge, getSourceTypeMeta } from '@/features/sources/source-ui'
import type { SourceListItem, SourceStatus, SourceType } from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import {
  Database as DatabaseIcon,
  Eye,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  SearchX,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { useDeferredValue, useMemo, useState } from 'react'
import { toast } from 'sonner'

const DATABASE_TYPES: readonly SourceType[] = ['postgresql', 'mysql', 'mssql', 'mongodb']
const FILE_TYPES: readonly SourceType[] = [
  'pdf',
  'docx',
  'xlsx',
  'csv',
  'txt',
  'markdown',
  'file_upload',
]
const WEB_TYPES: readonly SourceType[] = ['web_url']
const INTEGRATION_TYPES: readonly SourceType[] = [
  'confluence',
  'sharepoint',
  'google_drive',
  'notion',
]

const TYPE_GROUP_LABEL: Record<Exclude<TypeGroup, 'all'>, string> = {
  database: 'Database',
  file: 'Files',
  web: 'Web',
  integration: 'Integration',
}

const STATUS_DOT_CLASS: Record<string, string> = {
  pending: 'bg-zinc-400',
  syncing: 'bg-blue-500 animate-pulse',
  running: 'bg-blue-500 animate-pulse',
  ready: 'bg-emerald-500',
  completed: 'bg-emerald-500',
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  failed: 'bg-red-500',
  disabled: 'bg-zinc-300 dark:bg-zinc-600',
}

const STATUS_TEXT_CLASS: Record<string, string> = {
  pending: 'text-zinc-600 dark:text-zinc-300',
  syncing: 'text-blue-700 dark:text-blue-300',
  running: 'text-blue-700 dark:text-blue-300',
  ready: 'text-emerald-700 dark:text-emerald-300',
  completed: 'text-emerald-700 dark:text-emerald-300',
  success: 'text-emerald-700 dark:text-emerald-300',
  error: 'text-red-700 dark:text-red-300',
  failed: 'text-red-700 dark:text-red-300',
  disabled: 'text-zinc-500 dark:text-zinc-400',
}

function getTypeGroup(type: SourceType | string): Exclude<TypeGroup, 'all'> | 'other' {
  if ((DATABASE_TYPES as readonly string[]).includes(type)) return 'database'
  if ((FILE_TYPES as readonly string[]).includes(type)) return 'file'
  if ((WEB_TYPES as readonly string[]).includes(type)) return 'web'
  if ((INTEGRATION_TYPES as readonly string[]).includes(type)) return 'integration'
  return 'other'
}

function StatusDot({ status }: { status: SourceStatus | string | undefined | null }) {
  const value = (status ?? 'pending') as string
  const dot = STATUS_DOT_CLASS[value] ?? STATUS_DOT_CLASS.disabled
  const text = STATUS_TEXT_CLASS[value] ?? STATUS_TEXT_CLASS.disabled
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium">
      <span className={cn('h-2 w-2 rounded-full', dot)} aria-hidden />
      <span className={cn('capitalize', text)}>{value}</span>
    </span>
  )
}

function TypePill({ type }: { type: SourceType | string }) {
  const meta = getSourceTypeMeta(type)
  const group = getTypeGroup(type)
  const groupLabel = group === 'other' ? meta.label : TYPE_GROUP_LABEL[group]
  const showSubLabel = group !== 'other' && groupLabel !== meta.label
  return (
    <span className="inline-flex items-center gap-2 rounded-md border bg-muted/40 px-2 py-1 text-xs">
      <meta.icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span className="font-medium text-foreground">{groupLabel}</span>
      {showSubLabel ? <span className="text-muted-foreground">· {meta.label}</span> : null}
    </span>
  )
}

function SourceRowActions({
  source,
  isSyncing,
  onSync,
  onDelete,
}: {
  source: SourceListItem
  isSyncing: boolean
  onSync: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        aria-label={`Sync ${source.name}`}
        onClick={() => onSync(source.id)}
        disabled={isSyncing}
        className="h-8 gap-1.5 px-2 text-xs"
      >
        {isSyncing ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
        )}
        Sync
      </Button>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`More actions for ${source.name}`}
            className="h-8 w-8 p-0"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-44 p-1">
          <Link
            href={`/admin/sources/${source.id}`}
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
          >
            <Eye className="h-4 w-4" aria-hidden />
            View details
          </Link>
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              onDelete(source.id)
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            Delete
          </button>
        </PopoverContent>
      </Popover>
    </div>
  )
}

const SKELETON_ROW_KEYS = ['s1', 's2', 's3', 's4', 's5'] as const

export function SourcesTableSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="ml-auto h-9 w-24" />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {['c1', 'c2', 'c3', 'c4', 'c5'].map((key) => (
          <Skeleton key={key} className="h-7 w-20 rounded-full" />
        ))}
      </div>
      <div className="rounded-md border">
        <div className="space-y-px">
          {SKELETON_ROW_KEYS.map((key) => (
            <Skeleton key={key} className="h-14 w-full rounded-none" />
          ))}
        </div>
      </div>
    </div>
  )
}

interface SourcesEmptyProps {
  filtered: boolean
  onClearFilters?: () => void
}

function SourcesEmpty({ filtered, onClearFilters }: SourcesEmptyProps) {
  if (filtered) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border/70 bg-muted/20 px-6 py-12 text-center">
        <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">No sources match your filters</p>
          <p className="text-sm text-muted-foreground">
            Try removing a filter or adjusting your search.
          </p>
        </div>
        {onClearFilters ? (
          <Button variant="outline" size="sm" onClick={onClearFilters}>
            Clear filters
          </Button>
        ) : null}
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border/70 bg-muted/20 px-6 py-16 text-center">
      <DatabaseIcon className="h-10 w-10 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <h3 className="text-base font-semibold">No sources yet</h3>
        <p className="max-w-sm text-sm text-muted-foreground">
          Connect a knowledge source to start indexing documents and surface answers in chat.
        </p>
      </div>
      <Button asChild>
        <Link href="/admin/sources/new">Add your first source</Link>
      </Button>
    </div>
  )
}

export function SourcesTable() {
  const { data, isLoading } = useListSources()
  const deleteMutation = useDeleteSource()
  const syncMutation = useTriggerSync()

  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [syncingAll, setSyncingAll] = useState(false)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeGroup>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const deferredSearch = useDeferredValue(search)
  const sources = useMemo(() => data?.items ?? [], [data?.items])

  const filtersActive =
    deferredSearch.trim().length > 0 || typeFilter !== 'all' || statusFilter !== 'all'

  const filtered = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase()
    return sources.filter((source) => {
      const matchName = needle.length === 0 || source.name.toLowerCase().includes(needle)
      const matchType = typeFilter === 'all' || getTypeGroup(source.source_type) === typeFilter
      const matchStatus = statusFilter === 'all' || (source.status ?? 'pending') === statusFilter
      return matchName && matchType && matchStatus
    })
  }, [sources, deferredSearch, typeFilter, statusFilter])

  const syncCandidates = useMemo(
    () => sources.filter((s) => s.is_active && s.status !== 'syncing'),
    [sources]
  )

  function clearFilters() {
    setSearch('')
    setTypeFilter('all')
    setStatusFilter('all')
  }

  function handleSyncOne(id: string) {
    syncMutation.mutate(id, {
      onSuccess: () => toast.success('Sync started'),
      onError: (err) => toast.error(getErrorMessage(err) || 'Sync failed'),
    })
  }

  async function handleSyncAll() {
    if (syncCandidates.length === 0) return
    setSyncingAll(true)
    let started = 0
    let failed = 0
    for (const source of syncCandidates) {
      try {
        await syncMutation.mutateAsync(source.id)
        started += 1
      } catch {
        failed += 1
      }
    }
    setSyncingAll(false)
    if (failed === 0) {
      toast.success(`Sync started for ${started} ${started === 1 ? 'source' : 'sources'}`)
    } else {
      toast.error(`Started ${started}, failed ${failed}. Check sources for errors.`)
    }
  }

  if (isLoading) {
    return <SourcesTableSkeleton />
  }

  if (sources.length === 0) {
    return <SourcesEmpty filtered={false} />
  }

  const showEmptyFiltered = filtered.length === 0 && filtersActive

  return (
    <div className="space-y-4">
      <SourcesToolbar
        search={search}
        onSearchChange={setSearch}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        totalCount={filtered.length}
        syncCandidateCount={syncCandidates.length}
        onSyncAll={handleSyncAll}
        isSyncingAll={syncingAll}
      />

      {showEmptyFiltered ? (
        <SourcesEmpty filtered onClearFilters={clearFilters} />
      ) : (
        <>
          {/* Mobile card list */}
          <div className="space-y-3 sm:hidden">
            {filtered.map((source) => (
              <SourceRowCard
                key={source.id}
                source={source}
                isSyncing={syncMutation.isPending && syncMutation.variables === source.id}
                onSync={handleSyncOne}
                onDelete={setDeletingId}
              />
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden overflow-hidden rounded-md border sm:block">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/75">
                <TableRow>
                  <TableHead className="min-w-[220px]">Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead className="text-right">Documents</TableHead>
                  <TableHead>Last synced</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((source) => {
                  const meta = getSourceTypeMeta(source.source_type)
                  const documents = source.latest_job?.documents_indexed
                  const isRowSyncing =
                    syncMutation.isPending && syncMutation.variables === source.id

                  return (
                    <TableRow key={source.id} className="group transition-colors hover:bg-muted/30">
                      <TableCell className="py-3">
                        <div className="flex items-start gap-3">
                          <span
                            className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground transition-colors group-hover:bg-background"
                            aria-hidden
                          >
                            <meta.icon className="h-3.5 w-3.5" />
                          </span>
                          <div className="min-w-0">
                            <Link
                              href={`/admin/sources/${source.id}`}
                              className="block truncate font-medium hover:underline"
                            >
                              {source.name}
                            </Link>
                            <p className="truncate text-xs text-muted-foreground">
                              {source.description?.trim() ? source.description : meta.label}
                            </p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <TypePill type={source.source_type} />
                      </TableCell>
                      <TableCell>
                        <StatusDot status={source.status} />
                      </TableCell>
                      <TableCell>
                        <SourceModeBadge mode={source.source_mode} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {typeof documents === 'number' ? documents.toLocaleString() : '—'}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelative(source.last_synced_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <SourceRowActions
                          source={source}
                          isSyncing={isRowSyncing}
                          onSync={handleSyncOne}
                          onDelete={setDeletingId}
                        />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      <AlertDialog
        open={Boolean(deletingId)}
        onOpenChange={(next) => {
          if (!next) setDeletingId(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete source?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The source and all its associated permissions will be
              permanently removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deletingId) {
                  deleteMutation.mutate(deletingId, {
                    onSettled: () => setDeletingId(null),
                  })
                }
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
