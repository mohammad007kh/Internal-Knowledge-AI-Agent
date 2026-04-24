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
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatTimestamp,
  getSourceTypeMeta,
  SourceModeBadge,
  StatusBadge,
} from '@/features/sources/source-ui'
import {
  useDeleteSource,
  useListSources,
  useTriggerSync,
} from '@/features/sources/hooks/useSources'
import type { SourceListItem, SourceType } from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import {
  Database as DatabaseIcon,
  Eye,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  Search as SearchIcon,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { useDeferredValue, useMemo, useState } from 'react'
import { toast } from 'sonner'

type TypeGroup = 'all' | 'database' | 'file' | 'web' | 'integration'
type StatusFilter = 'all' | 'pending' | 'syncing' | 'ready' | 'error' | 'disabled'

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

function getTypeGroup(type: SourceType | string): Exclude<TypeGroup, 'all'> | 'other' {
  if ((DATABASE_TYPES as readonly string[]).includes(type)) return 'database'
  if ((FILE_TYPES as readonly string[]).includes(type)) return 'file'
  if ((WEB_TYPES as readonly string[]).includes(type)) return 'web'
  if ((INTEGRATION_TYPES as readonly string[]).includes(type)) return 'integration'
  return 'other'
}

function TypeIcon({ type }: { type: SourceType | string }) {
  const { icon: Icon, label } = getSourceTypeMeta(type)
  return (
    <span className="inline-flex items-center" title={label}>
      <Icon className="h-4 w-4 text-muted-foreground" aria-label={label} />
    </span>
  )
}

function SourceRowActions({
  source,
  onDelete,
}: {
  source: SourceListItem
  onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const syncMutation = useTriggerSync()
  const isSyncing = syncMutation.isPending && syncMutation.variables === source.id

  return (
    <div className="flex items-center justify-end gap-2">
      <Button
        variant="outline"
        size="sm"
        aria-label={`Sync source ${source.name}`}
        onClick={() =>
          syncMutation.mutate(source.id, {
            onSuccess: () => toast.success('Sync started'),
            onError: (err) => toast.error(getErrorMessage(err) || 'Sync failed'),
          })
        }
        disabled={isSyncing}
      >
        {isSyncing ? (
          <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="mr-1 h-4 w-4" aria-hidden />
        )}
        Sync Now
      </Button>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`More actions for ${source.name}`}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-40 p-1">
          <Link
            href={`/admin/sources/${source.id}`}
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
          >
            <Eye className="h-4 w-4" aria-hidden />
            View
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

export function SourcesTableSkeleton() {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10" />
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Mode</TableHead>
            <TableHead className="text-right">Documents</TableHead>
            <TableHead>Last Synced</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 5 }).map((_, i) => (
            <TableRow key={i}>
              <TableCell>
                <Skeleton className="h-4 w-4" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-40" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-5 w-16" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-5 w-20" />
              </TableCell>
              <TableCell className="text-right">
                <Skeleton className="ml-auto h-4 w-10" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-32" />
              </TableCell>
              <TableCell>
                <Skeleton className="ml-auto h-8 w-32" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function SourcesTable() {
  const { data, isLoading } = useListSources()
  const deleteMutation = useDeleteSource()
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeGroup>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const deferredSearch = useDeferredValue(search)
  const sources = data?.items ?? []

  const filtersActive =
    deferredSearch.trim().length > 0 || typeFilter !== 'all' || statusFilter !== 'all'

  const filtered = useMemo(() => {
    const needle = deferredSearch.trim().toLowerCase()
    return sources.filter((s) => {
      const matchName = needle.length === 0 || s.name.toLowerCase().includes(needle)
      const matchType = typeFilter === 'all' || getTypeGroup(s.source_type) === typeFilter
      const matchStatus =
        statusFilter === 'all' || (s.status ?? 'pending') === statusFilter
      return matchName && matchType && matchStatus
    })
  }, [sources, deferredSearch, typeFilter, statusFilter])

  if (isLoading) {
    return <SourcesTableSkeleton />
  }

  if (sources.length === 0 && !filtersActive) {
    return (
      <EmptyState
        icon={DatabaseIcon}
        title="No sources yet"
        description="Add a source to start indexing documents"
        action={{ label: 'Add source', href: '/admin/sources/new' }}
      />
    )
  }

  return (
    <>
      <div className="flex flex-col gap-3 pb-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <SearchIcon
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sources…"
            aria-label="Search sources"
            className="pl-9"
          />
        </div>
        <Select
          value={typeFilter}
          onValueChange={(v) => setTypeFilter(v as TypeGroup)}
        >
          <SelectTrigger className="sm:w-40" aria-label="Filter by type">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="database">Database</SelectItem>
            <SelectItem value="file">File</SelectItem>
            <SelectItem value="web">Web</SelectItem>
            <SelectItem value="integration">Integration</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as StatusFilter)}
        >
          <SelectTrigger className="sm:w-40" aria-label="Filter by status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="syncing">Syncing</SelectItem>
            <SelectItem value="ready">Ready</SelectItem>
            <SelectItem value="error">Error</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableCaption className="sr-only">Sources list</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" aria-label="Type" />
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead className="text-right">Documents</TableHead>
              <TableHead>Last Synced</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-10 text-center text-sm text-muted-foreground"
                >
                  No sources match your filters.
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((source) => {
                const documents = source.latest_job?.documents_indexed
                return (
                  <TableRow key={source.id}>
                    <TableCell>
                      <TypeIcon type={source.source_type} />
                    </TableCell>
                    <TableCell className="font-medium">
                      <Link
                        href={`/admin/sources/${source.id}`}
                        className="hover:underline"
                      >
                        {source.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={source.status} />
                    </TableCell>
                    <TableCell>
                      <SourceModeBadge mode={source.source_mode} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {typeof documents === 'number' ? documents : '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatTimestamp(source.last_synced_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <SourceRowActions source={source} onDelete={setDeletingId} />
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>

      <AlertDialog
        open={!!deletingId}
        onOpenChange={(o) => !o && setDeletingId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete source?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The source and all its associated permissions will
              be permanently removed.
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
    </>
  )
}
