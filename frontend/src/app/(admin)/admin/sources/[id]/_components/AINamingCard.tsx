'use client'

/**
 * AINamingCard — the AI-naming assistant card on the Settings tab.
 *
 * Replaces the legacy "AI Description" card on the Overview tab AND the
 * proposed-description / proposed-name dialogs that used to write directly
 * via `useUpdateSource`. New flow:
 *
 *   1. Admin clicks "Regenerate description" or "Regenerate both".
 *   2. Hook fires (`refreshDescriptionApi` / `autoNameApi`); we receive the
 *      proposed text.
 *   3. We render a side-by-side current-vs-proposed diff. Admin clicks
 *      Accept → we call `onApply({ name?, description? })`, which the parent
 *      uses to call `form.setValue(...)` with `shouldDirty: true`. The
 *      sticky save bar at the bottom of the form lights up; admin reviews
 *      and clicks Save changes; the existing form-submit path persists.
 *   4. Discard closes the diff with no form mutation.
 *
 * Single-writer invariant: the card never calls `useUpdateSource` itself.
 * Only `EditableSettingsForm.onSubmit` writes to the server. This eliminates
 * the race condition where a stale proposed-description Save could clobber
 * an in-flight form submit.
 *
 * Name protection: when "Regenerate both" is clicked AND the source's
 * current name has `name_status === 'user_set'`, we show a confirmation
 * AlertDialog before firing the auto-name request — replacing a name the
 * admin typed themselves should not be a one-click action.
 *
 * History view: we expose a "History (n)" link that opens a Sheet. The
 * underlying GET endpoint for `SourceDescriptionHistory` does not exist
 * yet — the Sheet renders a "History view coming soon" placeholder. The
 * count is not yet wired either.
 */

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  useAutoNameSource,
  useRefreshDescription,
} from '@/features/sources/hooks/useSources'
import type { NameStatus, SourceDetail } from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { SparklesIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { formatRelative } from './SyncStatusPill'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AINamingCardProps {
  source: SourceDetail
  /**
   * Called when the admin accepts a proposal. The parent form should call
   * `form.setValue(field, value, { shouldDirty: true })` so the sticky save
   * bar updates. `name` is omitted when only the description was regenerated.
   */
  onApply: (proposed: { name?: string; description: string }) => void
}

// ---------------------------------------------------------------------------
// Provenance line — derives copy from `name_status` / `description_status`
// ---------------------------------------------------------------------------

interface ProvenanceLineProps {
  label: 'Current name' | 'Current description'
  status: NameStatus | undefined
  updatedAt: string
  testId: string
}

function provenanceCopy(
  status: NameStatus | undefined,
  updatedAt: string
): { suffix: string; pending: boolean } {
  if (status === 'pending_ai') return { suffix: 'Naming…', pending: true }
  const when = formatRelative(updatedAt)
  if (status === 'ai_set') return { suffix: `AI-written · ${when}`, pending: false }
  // Default to user_set when undefined — older payloads omit the field.
  return { suffix: `User-edited · ${when}`, pending: false }
}

function ProvenanceLine({ label, status, updatedAt, testId }: ProvenanceLineProps) {
  const { suffix, pending } = provenanceCopy(status, updatedAt)
  return (
    <p
      className="text-xs text-muted-foreground"
      data-testid={testId}
      data-status={status ?? 'user_set'}
    >
      <span className="font-medium text-foreground/80">{label}:</span>{' '}
      <span className={cn(pending && 'animate-pulse italic')}>{suffix}</span>
    </p>
  )
}

// ---------------------------------------------------------------------------
// Diff preview dialog (replaces the old proposed-description Dialog)
// ---------------------------------------------------------------------------

interface DiffPayload {
  /** The proposed name; absent when only description was regenerated. */
  name?: string
  description: string
}

interface DiffDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  current: { name: string; description: string }
  proposed: DiffPayload | null
  onAccept: () => void
}

function DiffDialog({ open, onOpenChange, current, proposed, onAccept }: DiffDialogProps) {
  if (!proposed) return null
  const showName = typeof proposed.name === 'string'
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Review AI proposal</DialogTitle>
          <DialogDescription>
            Accept to fill the form. Nothing is saved until you click Save changes
            in the form below.
          </DialogDescription>
        </DialogHeader>
        <div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2"
          data-testid="ai-naming-diff"
        >
          <div className="space-y-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Current
            </p>
            {showName ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Name</p>
                <p className="break-words text-sm">{current.name}</p>
              </div>
            ) : null}
            <div>
              <p className="text-xs font-medium text-muted-foreground">Description</p>
              <p className="break-words text-sm">
                {current.description.trim().length > 0
                  ? current.description
                  : '(empty)'}
              </p>
            </div>
          </div>
          <div className="space-y-3 rounded-md border-l-2 border-primary pl-3">
            <p className="text-xs uppercase tracking-wide text-primary">Proposed</p>
            {showName ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Name</p>
                <p className="break-words text-sm font-medium">{proposed.name}</p>
              </div>
            ) : null}
            <div>
              <p className="text-xs font-medium text-muted-foreground">Description</p>
              <p className="break-words text-sm">{proposed.description}</p>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="ai-naming-diff-discard"
          >
            Discard
          </Button>
          <Button onClick={onAccept} data-testid="ai-naming-diff-accept">
            Accept
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Card body
// ---------------------------------------------------------------------------

export function AINamingCard({ source, onApply }: AINamingCardProps) {
  const refreshDesc = useRefreshDescription(source.id)
  const autoName = useAutoNameSource(source.id)

  const [proposed, setProposed] = useState<DiffPayload | null>(null)
  const [confirmRegenerateBoth, setConfirmRegenerateBoth] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)

  const isPending = refreshDesc.isPending || autoName.isPending
  const nameDays = (() => {
    if (!source.updated_at) return null
    const ms = Date.now() - new Date(source.updated_at).getTime()
    if (Number.isNaN(ms)) return null
    return Math.max(0, Math.round(ms / (1000 * 60 * 60 * 24)))
  })()

  function handleRegenerateDescription() {
    refreshDesc.mutate(undefined, {
      onSuccess: (data) => {
        setProposed({ description: data.proposed_description })
      },
      onError: (err) => toast.error(getErrorMessage(err)),
    })
  }

  function fireRegenerateBoth() {
    autoName.mutate(undefined, {
      onSuccess: (data) => {
        setProposed({
          name: data.proposed_name,
          description: data.proposed_description,
        })
      },
      onError: (err) => toast.error(getErrorMessage(err)),
    })
  }

  function handleRegenerateBothClick() {
    // Name protection: typed-by-admin names get a confirmation dialog before
    // we replace them with the AI's draft.
    if (source.name_status === 'user_set') {
      setConfirmRegenerateBoth(true)
      return
    }
    fireRegenerateBoth()
  }

  function handleAccept() {
    if (!proposed) return
    if (typeof proposed.name === 'string') {
      onApply({ name: proposed.name, description: proposed.description })
    } else {
      onApply({ description: proposed.description })
    }
    setProposed(null)
  }

  return (
    <>
      <Card data-testid="ai-naming-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <SparklesIcon className="h-4 w-4 text-primary" aria-hidden />
            AI naming assistant
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Drafts a clear, retrieval-friendly name and description by reading
            this source&apos;s content.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <ProvenanceLine
              label="Current name"
              status={source.name_status}
              updatedAt={source.updated_at}
              testId="ai-naming-name-provenance"
            />
            <ProvenanceLine
              label="Current description"
              status={source.description_status}
              updatedAt={source.updated_at}
              testId="ai-naming-description-provenance"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRegenerateDescription}
              disabled={isPending}
              data-testid="ai-naming-regenerate-description"
            >
              {refreshDesc.isPending ? 'Generating…' : 'Regenerate description'}
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={handleRegenerateBothClick}
              disabled={isPending}
              data-testid="ai-naming-regenerate-both"
            >
              {autoName.isPending ? 'Regenerating…' : 'Regenerate both'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setHistoryOpen(true)}
              data-testid="ai-naming-history-link"
              className="ml-auto"
            >
              <Badge variant="secondary" className="mr-1.5">
                History
              </Badge>
              View past descriptions
            </Button>
          </div>
        </CardContent>
      </Card>

      <DiffDialog
        open={!!proposed}
        onOpenChange={(open) => {
          if (!open) setProposed(null)
        }}
        current={{ name: source.name, description: source.description ?? '' }}
        proposed={proposed}
        onAccept={handleAccept}
      />

      {/* Name-protection confirmation. Only fires when the user typed the
          current name themselves and clicks "Regenerate both". */}
      <AlertDialog
        open={confirmRegenerateBoth}
        onOpenChange={setConfirmRegenerateBoth}
      >
        <AlertDialogContent data-testid="ai-naming-confirm-regenerate-both">
          <AlertDialogHeader>
            <AlertDialogTitle>Replace your typed name?</AlertDialogTitle>
            <AlertDialogDescription>
              {nameDays === null
                ? 'You typed this name yourself. Regenerating will replace it with the AI’s draft.'
                : `You typed this name ${nameDays} day${
                    nameDays === 1 ? '' : 's'
                  } ago. Regenerating will replace it with the AI’s draft.`}{' '}
              Continue?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirmRegenerateBoth(false)
                fireRegenerateBoth()
              }}
              data-testid="ai-naming-confirm-continue"
            >
              Continue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent
          side="right"
          className="w-full max-w-md p-6"
          data-testid="ai-naming-history-sheet"
        >
          <SheetTitle>Description history</SheetTitle>
          <SheetDescription className="mt-2">
            Past descriptions for this source.
          </SheetDescription>
          <div className="mt-6 rounded-md border bg-muted/20 p-4 text-sm text-muted-foreground">
            History view coming soon. Past descriptions will appear here once the
            audit endpoint ships.
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
