'use client'

import { AiModelPicker } from '@/components/admin/AiModelPicker'
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
import { useAiModels } from '@/hooks/use-ai-models'
import { useEmbedders } from '@/hooks/use-embedders'
import { useProviders } from '@/hooks/use-providers'
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { getErrorMessage } from '@/lib/errors'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { requirementsFor } from './stage-requirements'

/**
 * Provider keys whose vendors do not ship a native embedder offering
 * (design doc §6.5). Cross-family hints are suppressed for these LLM
 * providers because there's no "matching" embedder to suggest.
 */
const PROVIDERS_WITHOUT_NATIVE_EMBEDDER: ReadonlySet<string> = new Set(['anthropic'])

/**
 * Edit dialog for a pipeline stage.
 *
 * Post-rewire: replaces the inline provider/model/api_key fields with the
 * `AiModelPicker` (Combobox). Per-stage `temperature` / `max_tokens` /
 * `custom_prompt` overrides remain.
 */

interface EditStageDialogProps {
  stage: LlmStageConfig
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function EditStageDialog({ stage, open, onOpenChange }: EditStageDialogProps) {
  const updateMutation = useUpdateLlmStage()

  const [aiModelId, setAiModelId] = useState<string | null>(stage.ai_model?.id ?? null)
  const [temperature, setTemperature] = useState(stage.temperature)
  const [maxTokens, setMaxTokens] = useState(stage.max_tokens)
  const [customPrompt, setCustomPrompt] = useState(stage.custom_prompt ?? '')
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  useEffect(() => {
    if (open) {
      setAiModelId(stage.ai_model?.id ?? null)
      setTemperature(stage.temperature)
      setMaxTokens(stage.max_tokens)
      setCustomPrompt(stage.custom_prompt ?? '')
      setConfirmDiscard(false)
    }
  }, [open, stage])

  const requirement = requirementsFor(stage.stage)

  // Cross-family soft hint (design doc §6.5): when the picked LLM family
  // differs from the active embedder family, surface an amber callout. We
  // load these alongside the dialog so the hint reflects the user's
  // current selection in real time.
  const { data: aiModelsList } = useAiModels({ limit: 200 })
  const { data: activeEmbedderList } = useEmbedders({ active: true, limit: 1 })
  const { data: providersData } = useProviders()

  const pickedModel = useMemo(
    () => aiModelsList?.items.find((item) => item.id === aiModelId) ?? null,
    [aiModelsList, aiModelId]
  )
  const activeEmbedder = activeEmbedderList?.items[0] ?? null
  const familyByProviderKey = useMemo(() => {
    const map = new Map<string, string>()
    for (const provider of providersData?.providers ?? []) {
      map.set(provider.key, provider.family_tag)
    }
    return map
  }, [providersData])

  const llmProviderKey = pickedModel?.provider ?? null
  const llmFamily = llmProviderKey ? (familyByProviderKey.get(llmProviderKey) ?? null) : null
  const embedderFamily = activeEmbedder
    ? (familyByProviderKey.get(activeEmbedder.provider) ?? null)
    : null
  const showCrossFamilyHint =
    Boolean(llmProviderKey && llmFamily && embedderFamily) &&
    llmFamily !== embedderFamily &&
    !PROVIDERS_WITHOUT_NATIVE_EMBEDDER.has(llmProviderKey ?? '')

  const isDirty =
    aiModelId !== (stage.ai_model?.id ?? null) ||
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
    if (!aiModelId) {
      toast.error('Pick an AI model for this stage.')
      return
    }
    updateMutation.mutate(
      {
        stage: stage.stage,
        body: {
          ai_model_id: aiModelId,
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
            <AlertDialogAction
              onClick={() => {
                setConfirmDiscard(false)
                onOpenChange(false)
              }}
            >
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>Edit {stage.label}</DialogTitle>
            <DialogDescription>{stage.description}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`${stage.stage}-ai-model`}>AI Model</Label>
              <AiModelPicker
                id={`${stage.stage}-ai-model`}
                value={aiModelId}
                onChange={setAiModelId}
                requirement={requirement}
                placeholder="Select an AI model for this stage"
              />
              {requirement?.capabilities && requirement.capabilities.length > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Stage requires:{' '}
                  {requirement.capabilities.map((cap, idx, arr) => (
                    <span key={cap}>
                      <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                        {cap}
                      </code>
                      {idx < arr.length - 1 ? ', ' : ''}
                    </span>
                  ))}
                  {requirement.min_context_tokens
                    ? `, ≥ ${requirement.min_context_tokens.toLocaleString()} context tokens`
                    : ''}
                  .
                </p>
              ) : null}
              {showCrossFamilyHint && llmProviderKey ? (
                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs text-amber-900 dark:text-amber-200">
                  Most teams pair <code className="font-mono">{llmProviderKey}</code> LLMs with{' '}
                  <code className="font-mono">{llmProviderKey}</code> embedders for billing/key
                  consistency.
                </p>
              ) : null}
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
