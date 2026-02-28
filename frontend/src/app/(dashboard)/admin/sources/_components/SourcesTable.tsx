'use client'

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
import {
  useDeleteSource,
  useListSources,
  useTestConnection,
} from '@/features/sources/hooks/useSources'
import { Plug, Trash2 } from 'lucide-react'
import Link from 'next/link'

export function SourcesTable() {
  const { data, isLoading } = useListSources()
  const deleteMutation = useDeleteSource()
  const testMutation = useTestConnection()

  if (isLoading) {
    return <div className="py-8 text-center text-muted-foreground">Loading sources…</div>
  }

  const sources = data?.items ?? []

  if (sources.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground">
        No sources configured. Add one to get started.
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sources.map((source) => (
          <TableRow key={source.id}>
            <TableCell className="font-medium">
              <Link href={`/admin/sources/${source.id}/permissions`} className="hover:underline">
                {source.name}
              </Link>
            </TableCell>
            <TableCell>
              <Badge variant="secondary">{source.source_type}</Badge>
            </TableCell>
            <TableCell>
              {source.is_active ? (
                <Badge variant="default">Active</Badge>
              ) : (
                <Badge variant="outline">Inactive</Badge>
              )}
            </TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => testMutation.mutate(source.id)}
                  disabled={testMutation.isPending}
                >
                  <Plug className="mr-1 h-4 w-4" />
                  Test
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => deleteMutation.mutate(source.id)}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 className="mr-1 h-4 w-4" />
                  Delete
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
