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
import { useAiModelUsage, useDeleteAiModel, useUpdateAiModel } from '@/hooks/use-ai-models'
import type { AIModelPublic } from '@/types/ai-model'
import { Loader2Icon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

/**
 * Delete confirmation for an AI Model.
 *
 * Flow per design doc §8.1:
 *  1. Open dialog → fetch usage via `GET /{id}/usage`.
 *  2. If `total_references === 0` → standard "delete forever" confirmation.
 *  3. Otherwise → block hard delete; offer two paths:
 *     - **Archive**: PATCH `is_active = false` (soft-disable).
 *     - **Reassign**: link out to the affected stages so the admin can swap
 *       references first, then return to delete. v1 surfaces this as a
 *       guidance message — full inline reassignment is a v1.1 affordance.
 */

interface DeleteAiModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  model: AIModelPublic | null
}

export function DeleteAiModelDialog({ open, onOpenChange, model }: DeleteAiModelDialogProps) {
  // Only fire the usage call while the dialog is actually open and a model
  // is bound — see review fix #5.
  const usageQuery = useAiModelUsage(model?.id, { enabled: Boolean(model?.id && open) })
  const deleteMutation = useDeleteAiModel()
  const updateMutation = useUpdateAiModel()
  const [confirmHardDelete, setConfirmHardDelete] = useState(false)

  useEffect(() => {
    if (!open) setConfirmHardDelete(false)
  }, [open])

  if (!model) return null

  const usage = usageQuery.data
  const isLoading = usageQuery.isLoading
  const referenceCount = usage?.total_references ?? 0
  const inUse = referenceCount > 0

  function handleHardDelete() {
    if (!model) return
    deleteMutation.mutate(model.id, {
      onSuccess: () => {
        toast.success(`${model.name} deleted`)
        onOpenChange(false)
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : 'Failed to delete'
        toast.error(message)
      },
    })
  }

  function handleArchive() {
    if (!model) return
    updateMutation.mutate(
      { id: model.id, body: { is_active: false } },
      {
        onSuccess: () => {
          toast.success(`${model.name} archived (disabled)`)
          onOpenChange(false)
        },
        onError: (err) => {
          const message = err instanceof Error ? err.message : 'Failed to archive'
          toast.error(message)
        },
      }
    )
  }

  // The description is intentionally a single short sentence so it stays
  // valid HTML (no block-level children) and reads cleanly to assistive tech.
  // Structured content (stage list, guidance) sits as a sibling below.
  const descriptionText = isLoading
    ? 'Checking references before delete.'
    : inUse
      ? `This AI model is referenced by ${referenceCount} ${referenceCount === 1 ? 'resource' : 'resources'}. Hard delete is blocked until all references are reassigned.`
      : confirmHardDelete
        ? `This will permanently delete ${model.name}. This action cannot be undone.`
        : 'This AI model is not referenced by any pipeline stage or chat message and is safe to delete.'

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {model.name}?</AlertDialogTitle>
          <AlertDialogDescription>{descriptionText}</AlertDialogDescription>
        </AlertDialogHeader>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2Icon className="h-4 w-4 animate-spin" aria-hidden />
            Checking references…
          </div>
        ) : inUse ? (
          <div className="space-y-3 text-sm">
            {usage && usage.stages.length > 0 ? (
              <ul className="list-inside list-disc space-y-0.5 rounded-md bg-muted/40 p-3 text-xs">
                {usage.stages.map((stage) => (
                  <li key={stage.stage}>
                    <span className="font-medium">{stage.label}</span>
                    <span className="ml-1 font-mono text-muted-foreground">({stage.stage})</span>
                  </li>
                ))}
                {usage.chat_messages_count > 0 ? (
                  <li>
                    {usage.chat_messages_count.toLocaleString()} chat messages reference this model.
                  </li>
                ) : null}
              </ul>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Choose <strong>Archive</strong> to soft-disable this record (kept for audit, cannot be
              selected in pickers), or open{' '}
              <a href="/admin/llm-settings" className="font-medium text-primary hover:underline">
                /admin/llm-settings
              </a>{' '}
              to reassign each stage.
            </p>
          </div>
        ) : null}
        <AlertDialogFooter className="gap-2">
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          {!isLoading && inUse ? (
            <Button
              variant="outline"
              onClick={handleArchive}
              disabled={updateMutation.isPending || !model.is_active}
              title={!model.is_active ? 'Already archived' : undefined}
            >
              {updateMutation.isPending ? 'Archiving…' : 'Archive'}
            </Button>
          ) : null}
          {!isLoading && !inUse ? (
            confirmHardDelete ? (
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={handleHardDelete}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete forever'}
              </AlertDialogAction>
            ) : (
              <Button
                variant="destructive"
                onClick={() => setConfirmHardDelete(true)}
                disabled={deleteMutation.isPending}
              >
                Delete
              </Button>
            )
          ) : null}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
