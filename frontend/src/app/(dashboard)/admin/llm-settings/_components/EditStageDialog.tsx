'use client'

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
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { useEffect, useState } from 'react'

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

  // Reset form state when the dialog reopens for a different stage or the
  // underlying stage config changes.
  useEffect(() => {
    if (open) {
      setModel(stage.model)
      setApiKey('')
      setTemperature(stage.temperature)
      setMaxTokens(stage.max_tokens)
      setCustomPrompt(stage.custom_prompt ?? '')
    }
  }, [open, stage])

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
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor={`${stage.stage}-temperature`}>Temperature</Label>
              <Input
                id={`${stage.stage}-temperature`}
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
                required
              />
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
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
