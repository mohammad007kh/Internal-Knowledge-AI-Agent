'use client'

import { ActivateEmbedderDialog } from '@/app/(admin)/admin/embedders/_components/ActivateEmbedderDialog'
import { EmbedderFormSheet } from '@/app/(admin)/admin/embedders/_components/EmbedderFormSheet'
import { EmbeddersTable } from '@/app/(admin)/admin/embedders/_components/EmbeddersTable'
import { EmptyState } from '@/components/ui/EmptyState'
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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useDeleteEmbedder, useEmbedders } from '@/hooks/use-embedders'
import { getErrorMessage } from '@/lib/errors'
import type { EmbedderPublic } from '@/types/embedder'
import { Layers, PlusIcon, SearchIcon } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

const SKELETON_KEYS = ['e1', 'e2', 'e3', 'e4'] as const

/**
 * /admin/embedders — list view + Sheet-based create/edit + activate dialog.
 *
 * v1 invariant: exactly one active embedder. The Activate button on each row
 * opens `ActivateEmbedderDialog`, which dry-runs the preview before kicking
 * off the Celery re-embed job.
 */
export default function EmbeddersPage() {
  const searchParams = useSearchParams()
  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<EmbedderPublic | null>(null)
  const [deleting, setDeleting] = useState<EmbedderPublic | null>(null)
  const [activating, setActivating] = useState<EmbedderPublic | null>(null)

  const { data, isLoading, isError, error, refetch } = useEmbedders({
    q: search.trim() || undefined,
    limit: 100,
  })
  const deleteMutation = useDeleteEmbedder()

  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setEditing(null)
      setFormOpen(true)
    }
  }, [searchParams])

  const items = useMemo(() => data?.items ?? [], [data?.items])
  const totalCount = data?.total ?? 0
  const isEmpty = !isLoading && !isError && items.length === 0 && !search

  function openNewSheet() {
    setEditing(null)
    setFormOpen(true)
  }

  function openEditSheet(embedder: EmbedderPublic) {
    setEditing(embedder)
    setFormOpen(true)
  }

  function handleConfirmDelete() {
    if (!deleting) return
    deleteMutation.mutate(deleting.id, {
      onSuccess: () => {
        toast.success(`${deleting.name} deleted`)
        setDeleting(null)
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : 'Failed to delete'
        toast.error(message)
      },
    })
  }

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Embedders</h1>
          <p className="text-sm text-muted-foreground">
            Embedding endpoint records. v1 keeps a single active embedder; switching triggers a
            re-index batch job.
          </p>
        </div>
        <Button className="gap-1.5" onClick={openNewSheet}>
          <PlusIcon className="h-4 w-4" aria-hidden />
          New embedder
        </Button>
      </header>

      {isError ? (
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      ) : isEmpty ? (
        <EmptyState
          icon={Layers}
          title="No embedders configured"
          description="Add an embedder to power vector search. v1 ships with the legacy 1536-dim OpenAI embedder."
          action={{ label: 'Add embedder', onClick: openNewSheet }}
        />
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-sm">
              <SearchIcon
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name, provider, model ID…"
                className="pl-9"
                aria-label="Search embedders"
              />
            </div>
            {!isLoading ? (
              <span className="text-xs text-muted-foreground">
                {totalCount} {totalCount === 1 ? 'embedder' : 'embedders'}
              </span>
            ) : null}
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {SKELETON_KEYS.map((key) => (
                <Skeleton key={key} className="h-14 w-full" />
              ))}
            </div>
          ) : (
            <div className="rounded-md border">
              <EmbeddersTable
                items={items}
                onEdit={openEditSheet}
                onDelete={setDeleting}
                onActivate={setActivating}
              />
            </div>
          )}
        </div>
      )}

      <EmbedderFormSheet open={formOpen} onOpenChange={setFormOpen} embedder={editing} />
      <ActivateEmbedderDialog
        open={Boolean(activating)}
        onOpenChange={(next) => {
          if (!next) setActivating(null)
        }}
        embedder={activating}
      />

      <AlertDialog
        open={Boolean(deleting)}
        onOpenChange={(next) => {
          if (!next) setDeleting(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting?.is_active
                ? 'Active embedders cannot be deleted. Activate a different embedder first.'
                : deleting && deleting.in_use_chunks > 0
                  ? `This embedder is referenced by ${deleting.in_use_chunks.toLocaleString()} chunks. Deletion will be blocked by the API.`
                  : 'This action cannot be undone.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={Boolean(deleting?.is_active) || deleteMutation.isPending}
              onClick={(event) => {
                event.preventDefault()
                handleConfirmDelete()
              }}
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
