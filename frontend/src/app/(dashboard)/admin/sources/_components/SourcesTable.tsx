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
import { useState } from 'react'

export function SourcesTable() {
  const { data, isLoading } = useListSources()
  const deleteMutation = useDeleteSource()
  const testMutation = useTestConnection()
  const [deletingId, setDeletingId] = useState<string | null>(null)

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
    <>
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
                    onClick={() => setDeletingId(source.id)}
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

      <AlertDialog open={!!deletingId} onOpenChange={(o) => !o && setDeletingId(null)}>
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
              onClick={() => {
                if (deletingId) {
                  deleteMutation.mutate(deletingId, { onSettled: () => setDeletingId(null) })
                }
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
