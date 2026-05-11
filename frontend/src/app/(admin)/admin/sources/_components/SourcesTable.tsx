'use client'

import { ActionCell } from '@/app/(admin)/admin/sources/_components/ActionCell'
import { DatabaseStudyStrip } from '@/app/(admin)/admin/sources/_components/DatabaseStudyStrip'
import { IngestionStrip } from '@/app/(admin)/admin/sources/_components/IngestionStrip'
import { PendingNamePill } from '@/app/(admin)/admin/sources/_components/PendingNamePill'
import { SourceActionCell } from '@/app/(admin)/admin/sources/_components/SourceActionCell'
import { SourceRowCard } from '@/app/(admin)/admin/sources/_components/SourceRowCard'
import {
  SourcesToolbar,
  type StatusFilter,
  type TypeGroup,
} from '@/app/(admin)/admin/sources/_components/SourcesToolbar'
import { derivePhase } from '@/app/(admin)/admin/sources/_components/sourcePhase'
import { sourceKindOf } from '@/app/(admin)/admin/sources/[id]/_components/sourceTypeMatrix'
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
  sourcesKeys,
  useDeleteSource,
  useListSources,
  useTriggerSync,
} from '@/features/sources/hooks/useSources'
import { SourceModeBadge, getSourceTypeMeta } from '@/features/sources/source-ui'
import { updateSourceApi } from '@/lib/api/sources'
import type { SourceListItem, SourceType } from '@/lib/api/sources'
import { useQueryClient } from '@tanstack/react-query'
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

const TYPE_GROUP_LABEL: Record<Exclude<TypeGroup, 'all'>, string> = {
  database: 'Database',
  file: 'Files',
  web: 'Web',
  integration: 'Integration',
}

/**
 * Map a source type onto a toolbar filter group.
 *
 * Delegates to `sourceKindOf` — the single source of truth for "what coarse
 * kind is this type" (FX6/FX8). The backend StrEnum emits `'database'` (not a
 * per-dialect string), `'file_upload'`, `'web_url'`, `'confluence'`,
 * `'sharepoint'`; `sourceKindOf` already handles every value plus the
 * forward-compat dialect extras. The only mapping wrinkle: `sourceKindOf`
 * names SaaS connectors `'connector'` while the toolbar calls that group
 * `'integration'`.
 */
export function getTypeGroup(type: SourceType | string): Exclude<TypeGroup, 'all'> {
  const kind = sourceKindOf(type as SourceType)
  return kind === 'connector' ? 'integration' : kind
}

function TypePill({ type }: { type: SourceType | string }) {
  const meta = getSourceTypeMeta(type)
  const group = getTypeGroup(type)
  const groupLabel = TYPE_GROUP_LABEL[group]
  const showSubLabel = groupLabel !== meta.label
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

interface SourcesTableProps {
  /**
   * Optional canned dataset for visual QA / `?demo=db-states` mode. When
   * provided, the table renders these rows instead of the live API result and
   * skips polling. Wave 1D ships the demo set so designers can audit every
   * DB-source state without having to seed a real database.
   */
  demoSources?: readonly SourceListItem[]
}

export function SourcesTable({ demoSources }: SourcesTableProps = {}) {
  // Read without polling first to compute whether any row is in `running`
  // phase. Then re-subscribe with `pollWhileRunning` so the verb column
  // transitions out of "Working on it…" promptly. Both calls share a single
  // React Query cache entry (same query key), so this is one network request.
  const queryClient = useQueryClient()
  const { data: pollingProbe } = useListSources()
  const probeSources = useMemo(() => pollingProbe?.items ?? [], [pollingProbe?.items])
  const hasRunningRow = useMemo(
    () => probeSources.some((s) => derivePhase(s) === 'running'),
    [probeSources]
  )

  const { data, isLoading } = useListSources({ pollWhileRunning: hasRunningRow })
  const deleteMutation = useDeleteSource()
  const syncMutation = useTriggerSync()

  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [syncingAll, setSyncingAll] = useState(false)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeGroup>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const deferredSearch = useDeferredValue(search)
  const sources = useMemo<readonly SourceListItem[]>(
    () => demoSources ?? data?.items ?? [],
    [demoSources, data?.items]
  )

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

  // Approve = flip is_active=true. The verb cell's "Approve & ingest"
  // button calls this; the row's IngestionStrip immediately reflects the
  // new state via the React Query invalidation below.
  // useUpdateSource is keyed by sourceId so we can't share one instance
  // across rows — call updateSourceApi directly and invalidate the list
  // ourselves.
  async function handleApprove(id: string) {
    try {
      await updateSourceApi(id, { is_active: true })
      await queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      await queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(id) })
      toast.success('Source approved — now available to users')
    } catch (err) {
      toast.error(getErrorMessage(err) || 'Approval failed')
    }
  }

  // DB-source "Re-study" / "Schema drift detected · Re-study" branch.
  // The studying-agent endpoint isn't wired yet; for now route to the same
  // sync trigger which the worker treats as a re-study request for DB
  // sources. When the dedicated POST /sources/{id}/study endpoint lands
  // this handler swaps to it without changing the verb-cell contract.
  function handleStudy(id: string) {
    syncMutation.mutate(id, {
      onSuccess: () => toast.success('Schema study queued'),
      onError: (err) =>
        toast.error(getErrorMessage(err) || 'Failed to queue schema study'),
    })
  }

  // "Retry" on the failure branches of the verb cell. Identical to a
  // Sync trigger today — the worker re-runs the pipeline and clears the
  // failure on success. View-error opens the popover the verb cell
  // already manages locally; we don't need a handler for it at this level.
  function handleRetry(id: string) {
    syncMutation.mutate(id, {
      onSuccess: () => toast.success('Retry started'),
      onError: (err) => toast.error(getErrorMessage(err) || 'Retry failed'),
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
                onDelete={setDeletingId}
                onApprove={handleApprove}
                onSync={handleSyncOne}
                onStudy={handleStudy}
                onRetry={handleRetry}
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
                  <TableHead>Mode</TableHead>
                  <TableHead className="min-w-[180px]">Next step</TableHead>
                  <TableHead className="min-w-[320px]">Ingestion</TableHead>
                  <TableHead>Last synced</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((source) => {
                  const meta = getSourceTypeMeta(source.source_type)
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
                            {source.name_status === 'pending_ai' ? (
                              <Link
                                href={`/admin/sources/${source.id}`}
                                className="block hover:underline"
                                aria-label={`Naming in progress for source ${source.id}`}
                              >
                                <PendingNamePill />
                              </Link>
                            ) : (
                              <Link
                                href={`/admin/sources/${source.id}`}
                                className="block truncate font-medium hover:underline"
                              >
                                {source.name}
                              </Link>
                            )}
                            <p className="truncate text-xs text-muted-foreground">
                              {source.description_status === 'pending_ai'
                                ? '—'
                                : source.description?.trim()
                                  ? source.description
                                  : meta.label}
                            </p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <TypePill type={source.source_type} />
                      </TableCell>
                      <TableCell>
                        <SourceModeBadge mode={source.source_mode} />
                      </TableCell>
                      <TableCell>
                        <SourceActionCell
                          source={source}
                          onApprove={handleApprove}
                          onSync={handleSyncOne}
                          onStudy={handleStudy}
                          onRetry={handleRetry}
                        />
                      </TableCell>
                      <TableCell>
                        {getTypeGroup(source.source_type) === 'database' ? (
                          <DatabaseStudyStrip
                            schemaStatus={source.schema_status ?? null}
                            studyState={source.study_state ?? null}
                            isApproved={source.is_active}
                            tablesDocumented={source.tables_documented ?? null}
                            lastErrorPhase={source.last_error_phase ?? null}
                            sourceName={source.name}
                          />
                        ) : (
                          <IngestionStrip source={source} />
                        )}
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
