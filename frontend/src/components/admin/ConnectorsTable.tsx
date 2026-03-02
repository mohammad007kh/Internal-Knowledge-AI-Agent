'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { useState } from 'react'

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { apiClient } from '@/lib/api-client'
import Link from 'next/link'
import { toast } from 'sonner'

export interface Connector {
  id: string
  name: string
  connector_type: string
  is_active: boolean
  source_count?: number
  last_tested_at?: string | null
}

interface ConnectorsResponse {
  items: Connector[]
  total: number
}

async function fetchConnectors(): Promise<ConnectorsResponse> {
  const res = await apiClient.get<ConnectorsResponse>('/connectors?page=1&page_size=20')
  return res.data
}

async function testConnector(id: string): Promise<void> {
  await apiClient.post(`/connectors/${id}/test`, {})
}

async function deleteConnector(id: string): Promise<void> {
  await apiClient.delete(`/connectors/${id}`)
}

function StatusBadge({ active }: { active: boolean }) {
  if (active) {
    return (
      <Badge className="bg-green-600/15 text-green-700 dark:text-green-400" variant="outline">
        active
      </Badge>
    )
  }
  return (
    <Badge className="bg-red-600/15 text-red-700 dark:text-red-400" variant="outline">
      error
    </Badge>
  )
}

export function ConnectorsTable() {
  const queryClient = useQueryClient()
  const [pendingDelete, setPendingDelete] = useState<Connector | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['connectors'],
    queryFn: fetchConnectors,
  })

  const columns: ColumnDef<Connector>[] = [
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <Link
          className="font-medium underline-offset-2 hover:underline"
          href={`/admin/connectors/${row.original.id}`}
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      accessorKey: 'connector_type',
      header: 'Type',
      cell: ({ row }) => <span className="font-mono text-sm">{row.original.connector_type}</span>,
    },
    {
      accessorKey: 'is_active',
      header: 'Status',
      cell: ({ row }) => <StatusBadge active={row.original.is_active} />,
    },
    {
      accessorKey: 'source_count',
      header: 'Sources',
      cell: ({ row }) => <span className="tabular-nums">{row.original.source_count ?? 0}</span>,
    },
    {
      accessorKey: 'last_tested_at',
      header: 'Last Tested',
      cell: ({ row }) =>
        row.original.last_tested_at
          ? new Date(row.original.last_tested_at).toLocaleString()
          : 'Never',
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const c = row.original
        return (
          <div className="flex items-center justify-end gap-2">
            <Button
              aria-label={`Test ${c.name}`}
              onClick={async () => {
                try {
                  await testConnector(c.id)
                  toast.success('Connection test passed')
                  await queryClient.invalidateQueries({ queryKey: ['connectors'] })
                } catch {
                  toast.error('Connection test failed')
                }
              }}
              size="sm"
              variant="ghost"
            >
              Test
            </Button>
            <Button aria-label={`Edit ${c.name}`} asChild size="sm" variant="ghost">
              <Link href={`/admin/connectors/${c.id}`}>Edit</Link>
            </Button>
            <Button
              aria-label={`Delete ${c.name}`}
              className="text-destructive hover:text-destructive"
              onClick={() => setPendingDelete(c)}
              size="sm"
              variant="ghost"
            >
              Delete
            </Button>
          </div>
        )
      },
    },
  ]

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  if (isLoading) {
    return <p className="text-muted-foreground py-4 text-sm">Loading connectors…</p>
  }

  return (
    <>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((h) => (
                  <TableHead key={h.id}>
                    {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell className="text-muted-foreground text-center" colSpan={columns.length}>
                  No connectors configured.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <AlertDialog
        onOpenChange={(open) => !open && setPendingDelete(null)}
        open={Boolean(pendingDelete)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete connector?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete <strong>{pendingDelete?.name}</strong> and all associated
              sources. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={async () => {
                if (!pendingDelete) return
                try {
                  await deleteConnector(pendingDelete.id)
                  toast.success('Connector deleted')
                  await queryClient.invalidateQueries({ queryKey: ['connectors'] })
                } catch {
                  toast.error('Failed to delete connector')
                }
                setPendingDelete(null)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
