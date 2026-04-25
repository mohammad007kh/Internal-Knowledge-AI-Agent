'use client'

import { AiModelFormSheet } from '@/app/(admin)/admin/ai-models/_components/AiModelFormSheet'
import { AiModelsTable } from '@/app/(admin)/admin/ai-models/_components/AiModelsTable'
import { DeleteAiModelDialog } from '@/app/(admin)/admin/ai-models/_components/DeleteAiModelDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAiModels } from '@/hooks/use-ai-models'
import { getErrorMessage } from '@/lib/errors'
import type { AIModelPublic } from '@/types/ai-model'
import { CpuIcon, PlusIcon, SearchIcon } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'

const SKELETON_KEYS = ['m1', 'm2', 'm3', 'm4'] as const

/**
 * /admin/ai-models — list view + Sheet-based create/edit.
 *
 * Supports `?new=1` deep-link from empty states elsewhere (LLM Settings,
 * source create flow) — opens the form sheet on mount.
 */
export default function AiModelsPage() {
  const searchParams = useSearchParams()
  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<AIModelPublic | null>(null)
  const [deleting, setDeleting] = useState<AIModelPublic | null>(null)

  const { data, isLoading, isError, error, refetch } = useAiModels({
    q: search.trim() || undefined,
    limit: 100,
  })

  // Open the create sheet when ?new=1 is present.
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

  function openEditSheet(model: AIModelPublic) {
    setEditing(model)
    setFormOpen(true)
  }

  function openDeleteDialog(model: AIModelPublic) {
    setDeleting(model)
  }

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">AI Models</h1>
          <p className="text-sm text-muted-foreground">
            Manage LLM endpoint records. Each pipeline stage references one of these.
          </p>
        </div>
        <Button className="gap-1.5" onClick={openNewSheet}>
          <PlusIcon className="h-4 w-4" aria-hidden />
          New AI model
        </Button>
      </header>

      {isError ? (
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      ) : isEmpty ? (
        <EmptyState
          icon={CpuIcon}
          title="No AI models configured"
          description="Add your first AI model to wire it into pipeline stages."
          action={{ label: 'Configure first AI model', onClick: openNewSheet }}
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
                aria-label="Search AI models"
              />
            </div>
            {!isLoading ? (
              <span className="text-xs text-muted-foreground">
                {totalCount} {totalCount === 1 ? 'model' : 'models'}
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
              <AiModelsTable items={items} onEdit={openEditSheet} onDelete={openDeleteDialog} />
            </div>
          )}
        </div>
      )}

      <AiModelFormSheet open={formOpen} onOpenChange={setFormOpen} model={editing} />
      <DeleteAiModelDialog
        open={Boolean(deleting)}
        onOpenChange={(next) => {
          if (!next) setDeleting(null)
        }}
        model={deleting}
      />
    </div>
  )
}
