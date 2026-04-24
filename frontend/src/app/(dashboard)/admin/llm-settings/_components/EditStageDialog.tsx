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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useUpdateLlmStage } from '@/features/llm-settings/hooks/useLlmSettings'
import { getErrorMessage } from '@/lib/errors'
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

interface EditStageDialogProps {
  stage: LlmStageConfig
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function EditStageDialog({ stage, open, onOpenChange }: EditStageDialogProps) {
  const updateMutation = useUpdateLlmStage()

  const [model, setModel] = useState(stage.model)
  const [apiKey, setApiKey] = useState('')
  const [temperature, setTemperature] = useState(stage.temperature)
  const [maxTokens, setMaxTokens] = useState(stage.max_tokens)
  const [customPrompt, setCustomPrompt] = useState(stage.custom_prompt ?? '')
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  useEffect(() => {
    if (open) {
      setModel(stage.model)
      setApiKey('')
      setTemperature(stage.temperature)
      setMaxTokens(stage.max_tokens)
      setCustomPrompt(stage.custom_prompt ?? '')
      setConfirmDiscard(false)
    }
  }, [open, stage])

  const isDirty =
    model !== stage.model ||
    apiKey !== '' ||
    temperature !== stage.temperature ||
    maxTokens !== stage.max_tokens ||
    customPrompt !== (stage.custom_prompt ?? '')

  function handleOpenChange(next: boolean) {
    if (!next && isDirty && !updateMutation.isPending) {
      setConfirmDiscard(true)
      return
    }
    onOpenChange(next)
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    updateMutation.mutate(
      {
        stage: stage.stage,
        body: {
          model,
          ...(apiKey ? { api_key: apiKey } : {}),
          temperature,
          max_tokens: maxTokens,
          custom_prompt: customPrompt ? customPrompt : null,
        },
      },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => toast.error(getErrorMessage(err) || 'Failed to save settings.'),
      }
    )
  }

  return (
    <>
      <AlertDialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes. Closing this dialog will discard them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction onClick={() => { setConfirmDiscard(false); onOpenChange(false) }}>
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>Edit {stage.label}</DialogTitle>
            <DialogDescription>{stage.description}</DialogDescription>
          </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={`${stage.stage}-model`}>Model</Label>
            <Input
              id={`${stage.stage}-model`}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o-mini"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${stage.stage}-api-key`}>API Key</Label>
            <Input
              id={`${stage.stage}-api-key`}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Leave blank to keep existing"
              autoComplete="new-password"
            />
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor={`${stage.stage}-temperature`}>Temperature</Label>
              <span className="text-xs tabular-nums text-muted-foreground">
                {temperature.toFixed(1)}
              </span>
            </div>
            <input
              id={`${stage.stage}-temperature`}
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              aria-label="Temperature"
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>Precise</span>
              <span>Balanced</span>
              <span>Creative</span>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${stage.stage}-max-tokens`}>Max Tokens</Label>
            <Input
              id={`${stage.stage}-max-tokens`}
              type="number"
              min={1}
              step={1}
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value))}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${stage.stage}-custom-prompt`}>Custom Prompt</Label>
            <Textarea
              id={`${stage.stage}-custom-prompt`}
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="Optional system prompt override"
              rows={5}
              className="font-mono text-sm"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMutation.isPending || !isDirty}>
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    </>
  )
}
