'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Loader2, RefreshCw, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQuery } from '@tanstack/react-query'

export type SourceStatus = 'pending' | 'syncing' | 'ready' | 'error' | 'disabled'

export interface KnowledgeSource {
  id: string
  name: string
  connector_type: string
  status: SourceStatus
  document_count: number
  last_synced_at: string | null
  created_at: string
}

interface SourcesResponse {
  items: KnowledgeSource[]
  total: number
  page: number
  page_size: number
}

const STATUS_VARIANT: Record<SourceStatus, string> = {
  pending: 'bg-yellow-600/15 text-yellow-700 dark:text-yellow-400',
  syncing: 'bg-blue-600/15 text-blue-700 dark:text-blue-400',
  ready: 'bg-green-600/15 text-green-700 dark:text-green-400',
  error: 'bg-red-600/15 text-red-700 dark:text-red-400',
  disabled: 'bg-zinc-600/15 text-zinc-500 dark:text-zinc-400',
}

function StatusBadge({ status }: { status: SourceStatus }) {
  return <Badge className={cn('capitalize', STATUS_VARIANT[status])}>{status}</Badge>
}

async function fetchSources(page: number): Promise<SourcesResponse> {
  const res = await apiClient.get<SourcesResponse>(`/sources?page=${page}&page_size=20`)
  return res.data
}

async function triggerSync(id: string): Promise<void> {
  await apiClient.post(`/sources/${id}/sync`)
}

async function deleteSource(id: string): Promise<void> {
  await apiClient.delete(`/sources/${id}`)
}

const columnHelper = createColumnHelper<KnowledgeSource>()

export function SourcesTable() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['sources', page],
    queryFn: () => fetchSources(page),
  })

  const syncMutation = useMutation({
    mutationFn: triggerSync,
    onSuccess: () => {
      toast.success('Sync triggered')
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: () => toast.error('Failed to trigger sync'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => {
      toast.success('Source deleted')
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: () => toast.error('Failed to delete source'),
  })

  const columns = [
    columnHelper.accessor('name', {
      header: 'Name',
      cell: (info) => (
        <Link
          href={`/admin/sources/${info.row.original.id}`}
          className="font-medium underline-offset-2 hover:underline"
        >
          {info.getValue()}
        </Link>
      ),
    }),
    columnHelper.accessor('connector_type', {
      header: 'Connector',
      cell: (info) => <span className="font-mono text-xs">{info.getValue()}</span>,
    }),
    columnHelper.accessor('status', {
      header: 'Status',
      cell: (info) => <StatusBadge status={info.getValue()} />,
    }),
    columnHelper.accessor('document_count', {
      header: 'Documents',
      cell: (info) => <span className="tabular-nums">{info.getValue().toLocaleString()}</span>,
    }),
    columnHelper.accessor('last_synced_at', {
      header: 'Last Synced',
      cell: (info) => {
        const val = info.getValue()
        return (
          <span className="text-muted-foreground text-sm">
            {val ? new Date(val).toLocaleString() : 'Never'}
          </span>
        )
      },
    }),
    columnHelper.display({
      id: 'actions',
      header: 'Actions',
      cell: (info) => {
        const source = info.row.original
        return (
          <div className="flex items-center gap-2">
            <Button
              aria-label={`Sync ${source.name}`}
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate(source.id)}
              size="sm"
              variant="ghost"
            >
              {syncMutation.isPending && syncMutation.variables === source.id ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild={true}>
                <Button aria-label={`Delete ${source.name}`} size="sm" variant="ghost">
                  <Trash2 className="h-4 w-4 text-red-500" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete source?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will permanently delete <strong>{source.name}</strong> and all indexed
                    documents and embeddings. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-red-600 hover:bg-red-700"
                    onClick={() => deleteMutation.mutate(source.id)}
                  >
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )
      },
    }),
  ]

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    rowCount: data?.total ?? 0,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    )
  }

  if (isError) {
    return <p className="text-destructive p-4 text-sm">Failed to load sources.</p>
  }

  const totalPages = Math.ceil((data?.total ?? 0) / 20)

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell className="text-muted-foreground text-center" colSpan={columns.length}>
                No sources found.
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <Button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            size="sm"
            variant="outline"
          >
            Previous
          </Button>
          <span className="text-muted-foreground text-sm">
            Page {page} of {totalPages}
          </span>
          <Button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            size="sm"
            variant="outline"
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
