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
import { Switch } from '@/components/ui/switch'
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
 * Fallback values used to seed the override sliders when:
 *  - the stage has no override set (`stage.temperature` / `stage.max_tokens`
 *    are null), and
 *  - the picked AI Model's defaults haven't loaded yet (or the model is
 *    unset).
 *
 * The user can edit the value once the override toggle is on. These are
 * sane neutral defaults — see backend `src/api/v1/admin/llm_settings.py`.
 */
const FALLBACK_TEMPERATURE = 0.7
const FALLBACK_MAX_TOKENS = 2048

/**
 * Edit dialog for a pipeline stage.
 *
 * Post-rewire: replaces the inline provider/model/api_key fields with the
 * `AiModelPicker` (Combobox). Per-stage `temperature` / `max_tokens` /
 * `custom_prompt` overrides remain.
 *
 * `stage.temperature` and `stage.max_tokens` are nullable post-rewire:
 * `null` means "inherit from the linked AI Model defaults". The dialog
 * exposes this via override toggles — when off, the form sends `null` and
 * the backend resolves the value at runtime.
 */

interface EditStageDialogProps {
  stage: LlmStageConfig
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function EditStageDialog({ stage, open, onOpenChange }: EditStageDialogProps) {
  const updateMutation = useUpdateLlmStage()

  const [aiModelId, setAiModelId] = useState<string | null>(stage.ai_model?.id ?? null)
  // `temperature` / `maxTokens` are always non-null numbers in local state
  // so the slider/input can render unconditionally. The "override" booleans
  // determine whether the value is sent to the backend or replaced with
  // `null` (= inherit from the linked AI Model defaults).
  const [temperature, setTemperature] = useState<number>(stage.temperature ?? FALLBACK_TEMPERATURE)
  const [maxTokens, setMaxTokens] = useState<number>(stage.max_tokens ?? FALLBACK_MAX_TOKENS)
  const [overrideTemperature, setOverrideTemperature] = useState<boolean>(
    stage.temperature !== null
  )
  const [overrideMaxTokens, setOverrideMaxTokens] = useState<boolean>(stage.max_tokens !== null)
  const [customPrompt, setCustomPrompt] = useState(stage.custom_prompt ?? '')
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  useEffect(() => {
    if (open) {
      setAiModelId(stage.ai_model?.id ?? null)
      setTemperature(stage.temperature ?? FALLBACK_TEMPERATURE)
      setMaxTokens(stage.max_tokens ?? FALLBACK_MAX_TOKENS)
      setOverrideTemperature(stage.temperature !== null)
      setOverrideMaxTokens(stage.max_tokens !== null)
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

  // Defaults sourced from the picked AI Model when available. Used to
  // display "Default (X)" hints when the override toggle is off, so the
  // admin sees what value the backend will actually use.
  const modelDefaultTemperature = pickedModel?.default_temperature ?? null
  const modelDefaultMaxTokens = pickedModel?.default_max_tokens ?? null

  // What gets sent to the backend on save. `null` preserves the "inherit
  // from AI Model defaults" semantic.
  const effectiveTemperature: number | null = overrideTemperature ? temperature : null
  const effectiveMaxTokens: number | null = overrideMaxTokens ? maxTokens : null

  const isDirty =
    aiModelId !== (stage.ai_model?.id ?? null) ||
    effectiveTemperature !== stage.temperature ||
    effectiveMaxTokens !== stage.max_tokens ||
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
          // `null` preserves the "inherit from AI Model defaults" semantic
          // when the admin hasn't explicitly opted into an override.
          temperature: effectiveTemperature,
          max_tokens: effectiveMaxTokens,
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
                <div className="flex items-center gap-2">
                  {overrideTemperature ? (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {temperature.toFixed(1)}
                    </span>
                  ) : (
                    <span className="text-xs italic text-muted-foreground">
                      {modelDefaultTemperature !== null
                        ? `Model default (${modelDefaultTemperature.toFixed(1)})`
                        : 'Model default'}
                    </span>
                  )}
                  <Switch
                    checked={overrideTemperature}
                    onCheckedChange={setOverrideTemperature}
                    aria-label="Override temperature"
                  />
                </div>
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
                disabled={!overrideTemperature}
                className="w-full accent-primary disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="flex justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
                <span>Precise</span>
                <span>Balanced</span>
                <span>Creative</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor={`${stage.stage}-max-tokens`}>Max Tokens</Label>
                <div className="flex items-center gap-2">
                  {!overrideMaxTokens ? (
                    <span className="text-xs italic text-muted-foreground">
                      {modelDefaultMaxTokens !== null
                        ? `Model default (${modelDefaultMaxTokens})`
                        : 'Model default'}
                    </span>
                  ) : null}
                  <Switch
                    checked={overrideMaxTokens}
                    onCheckedChange={setOverrideMaxTokens}
                    aria-label="Override max tokens"
                  />
                </div>
              </div>
              <Input
                id={`${stage.stage}-max-tokens`}
                type="number"
                min={1}
                step={1}
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value))}
                disabled={!overrideMaxTokens}
                required={overrideMaxTokens}
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
