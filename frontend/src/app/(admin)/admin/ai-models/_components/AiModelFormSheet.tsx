'use client'

import { ApiKeyField } from '@/components/admin/ApiKeyField'
import { ProviderSelect } from '@/components/admin/ProviderSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useCreateAiModel, useTestAiModelConnection, useUpdateAiModel } from '@/hooks/use-ai-models'
import { useProvider } from '@/hooks/use-providers'
import { cn } from '@/lib/utils'
import type {
  AIModelCapabilities,
  AIModelCreateRequest,
  AIModelPublic,
  AIModelUpdateRequest,
} from '@/types/ai-model'
import type { ProviderSpec } from '@/types/provider'
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  Loader2Icon,
  ZapIcon,
} from 'lucide-react'
import { useEffect, useId, useMemo, useState } from 'react'
import { toast } from 'sonner'

/**
 * AI Model create/edit form, presented in a `Sheet` (per design doc §8.1).
 *
 * Sections:
 *   1. Identity — name, optional description (description currently lives in
 *      `extra_config.description` for forward-compat).
 *   2. Connection — provider select + base URL + model ID + API key.
 *   3. Generation defaults — temperature + max_tokens (collapsible Advanced).
 *   4. Test connection — uses the plaintext endpoint so the admin can
 *      validate before saving.
 *
 * `dimensions` is N/A here — that field lives on the embedder form.
 */

interface AiModelFormSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** When set, the sheet edits this record. Otherwise it creates a new one. */
  model: AIModelPublic | null
}

interface FormState {
  name: string
  description: string
  providerKey: string | null
  baseUrl: string
  modelId: string
  apiKey: string
  replaceApiKey: boolean
  defaultTemperature: number
  defaultMaxTokens: number
  capabilitiesJson: string
  isActive: boolean
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
  providerKey: null,
  baseUrl: '',
  modelId: '',
  apiKey: '',
  replaceApiKey: false,
  defaultTemperature: 0.7,
  defaultMaxTokens: 2048,
  capabilitiesJson: '{}',
  isActive: true,
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}

function readDescription(extra: Record<string, unknown> | null | undefined): string {
  if (!extra) return ''
  const candidate = extra.description
  if (typeof candidate === 'string') return candidate
  return ''
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '{}'
  }
}

export function AiModelFormSheet({ open, onOpenChange, model }: AiModelFormSheetProps) {
  const isEdit = Boolean(model)
  const formId = useId()
  const createMutation = useCreateAiModel()
  const updateMutation = useUpdateAiModel()
  const testMutation = useTestAiModelConnection()

  const [state, setState] = useState<FormState>(EMPTY_FORM)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [testResult, setTestResult] = useState<{
    ok: boolean
    text: string
  } | null>(null)
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null)

  const provider = useProvider(state.providerKey)
  const suggestedModels = useMemo<readonly string[]>(
    () => (provider ? provider.llm_models.map((m) => m.model_id) : []),
    [provider]
  )

  // Load form values when opened.
  useEffect(() => {
    if (!open) return
    if (model) {
      setState({
        name: model.name,
        description: readDescription(model.extra_config),
        providerKey: model.provider,
        baseUrl: model.base_url ?? '',
        modelId: model.model_id,
        apiKey: '',
        replaceApiKey: false,
        // Defensive null-coalescing: the backend schema declares these as
        // non-nullable with defaults, but older records or future schema
        // changes could leak null — keep the slider/input renderable.
        defaultTemperature: model.default_temperature ?? EMPTY_FORM.defaultTemperature,
        defaultMaxTokens: model.default_max_tokens ?? EMPTY_FORM.defaultMaxTokens,
        capabilitiesJson: safeStringify(model.capabilities),
        isActive: model.is_active,
      })
    } else {
      setState(EMPTY_FORM)
    }
    setTestResult(null)
    setCapabilitiesError(null)
    setAdvancedOpen(false)
  }, [open, model])

  function patch<K extends keyof FormState>(key: K, value: FormState[K]) {
    setState((prev) => ({ ...prev, [key]: value }))
  }

  function handleProviderChange(next: ProviderSpec) {
    setState((prev) => ({
      ...prev,
      providerKey: next.key,
      // Only auto-fill base URL if the user hasn't typed one yet, or if it
      // matches the previous provider's default (best-effort heuristic).
      baseUrl: prev.baseUrl === '' ? (next.default_base_url ?? '') : prev.baseUrl,
      modelId: prev.modelId === '' ? (next.llm_models[0]?.model_id ?? '') : prev.modelId,
    }))
  }

  function parseCapabilities(): AIModelCapabilities | undefined {
    const raw = state.capabilitiesJson.trim()
    if (raw === '' || raw === '{}') return {}
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>
      if (parsed === null || typeof parsed !== 'object') {
        throw new Error('Capabilities must be a JSON object.')
      }
      setCapabilitiesError(null)
      return parsed as AIModelCapabilities
    } catch (err) {
      setCapabilitiesError(describeError(err))
      return undefined
    }
  }

  function buildCreatePayload(): AIModelCreateRequest | null {
    if (!state.providerKey) {
      toast.error('Pick a provider first.')
      return null
    }
    if (!state.apiKey) {
      toast.error('API key is required for new AI models.')
      return null
    }
    const capabilities = parseCapabilities()
    if (capabilities === undefined) return null

    const extraConfig: Record<string, unknown> = {}
    if (state.description.trim()) extraConfig.description = state.description.trim()

    return {
      name: state.name.trim(),
      provider: state.providerKey,
      model_id: state.modelId.trim(),
      api_key: state.apiKey,
      base_url: state.baseUrl.trim() || null,
      extra_config: extraConfig,
      default_temperature: state.defaultTemperature,
      default_max_tokens: state.defaultMaxTokens,
      capabilities,
      is_active: state.isActive,
    }
  }

  function buildUpdatePayload(): AIModelUpdateRequest | null {
    if (!state.providerKey) {
      toast.error('Pick a provider first.')
      return null
    }
    const capabilities = parseCapabilities()
    if (capabilities === undefined) return null

    const extraConfig: Record<string, unknown> = {}
    if (state.description.trim()) extraConfig.description = state.description.trim()

    const payload: AIModelUpdateRequest = {
      name: state.name.trim(),
      provider: state.providerKey,
      model_id: state.modelId.trim(),
      base_url: state.baseUrl.trim() || null,
      extra_config: extraConfig,
      default_temperature: state.defaultTemperature,
      default_max_tokens: state.defaultMaxTokens,
      capabilities,
      is_active: state.isActive,
    }
    if (state.replaceApiKey) {
      if (!state.apiKey) {
        toast.error('Enter the new API key, or toggle "Keep existing key".')
        return null
      }
      payload.api_key = state.apiKey
    }
    return payload
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isEdit && model) {
      const payload = buildUpdatePayload()
      if (!payload) return
      updateMutation.mutate(
        { id: model.id, body: payload },
        {
          onSuccess: () => {
            toast.success('AI model updated')
            onOpenChange(false)
          },
          onError: (err) => toast.error(describeError(err)),
        }
      )
      return
    }
    const payload = buildCreatePayload()
    if (!payload) return
    createMutation.mutate(payload, {
      onSuccess: () => {
        toast.success('AI model created')
        onOpenChange(false)
      },
      onError: (err) => toast.error(describeError(err)),
    })
  }

  function handleTest() {
    if (!state.providerKey) {
      toast.error('Pick a provider before testing.')
      return
    }
    if (!state.modelId.trim()) {
      toast.error('Set a model ID before testing.')
      return
    }
    // For edit-mode without replace-mode, we have no plaintext key to send.
    // The plaintext endpoint requires the key — defer to the row-menu test
    // (record-bound) for that case.
    if (isEdit && !state.replaceApiKey) {
      toast.message('Use the row Test button to test the saved key.', {
        description: 'The form-level test uses the plaintext key you enter here.',
      })
      return
    }
    if (!state.apiKey) {
      toast.error('Enter an API key to test.')
      return
    }

    setTestResult(null)
    testMutation.mutate(
      {
        provider: state.providerKey,
        model_id: state.modelId.trim(),
        api_key: state.apiKey,
        base_url: state.baseUrl.trim() || null,
      },
      {
        onSuccess: (result) => {
          if (result.ok) {
            setTestResult({ ok: true, text: `Connected (${result.latency_ms ?? '—'} ms)` })
            toast.success('Connection OK')
          } else {
            setTestResult({ ok: false, text: result.error ?? 'Connection failed' })
            toast.error(result.error ?? 'Connection failed')
          }
        },
        onError: (err) => {
          const message = describeError(err)
          setTestResult({ ok: false, text: message })
          toast.error(message)
        },
      }
    )
  }

  const isSaving = createMutation.isPending || updateMutation.isPending
  const ids = {
    name: `${formId}-name`,
    description: `${formId}-description`,
    provider: `${formId}-provider`,
    baseUrl: `${formId}-base-url`,
    modelId: `${formId}-model-id`,
    apiKey: `${formId}-api-key`,
    temperature: `${formId}-temperature`,
    maxTokens: `${formId}-max-tokens`,
    capabilities: `${formId}-capabilities`,
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full max-w-xl flex-col overflow-hidden p-0 sm:max-w-xl"
      >
        <header className="border-b border-border px-6 py-4">
          <SheetTitle>{isEdit ? `Edit ${model?.name}` : 'New AI model'}</SheetTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            Endpoint credentials and generation defaults. API keys are encrypted at rest.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col overflow-y-auto"
          autoComplete="off"
        >
          <div className="space-y-6 px-6 py-5">
            {/* Identity */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Identity
              </h3>
              <div className="space-y-2">
                <Label htmlFor={ids.name}>
                  Name<span className="ml-1 text-destructive">*</span>
                </Label>
                <Input
                  id={ids.name}
                  value={state.name}
                  onChange={(e) => patch('name', e.target.value)}
                  placeholder="GPT-4o Production"
                  required
                  maxLength={150}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={ids.description}>Description</Label>
                <Textarea
                  id={ids.description}
                  value={state.description}
                  onChange={(e) => patch('description', e.target.value)}
                  placeholder="Optional — what this model is used for."
                  rows={2}
                  maxLength={300}
                />
              </div>
            </section>

            {/* Connection */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Connection
              </h3>
              <div className="space-y-2">
                <Label htmlFor={ids.provider}>
                  Provider<span className="ml-1 text-destructive">*</span>
                </Label>
                <ProviderSelect
                  id={ids.provider}
                  kind="llm"
                  value={state.providerKey}
                  onChange={handleProviderChange}
                  disabled={isSaving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={ids.baseUrl}>
                  Base URL
                  {provider?.base_url_required ? (
                    <span className="ml-1 text-destructive">*</span>
                  ) : null}
                </Label>
                <Input
                  id={ids.baseUrl}
                  value={state.baseUrl}
                  onChange={(e) => patch('baseUrl', e.target.value)}
                  placeholder={provider?.default_base_url ?? 'https://api.example.com/v1'}
                  required={provider?.base_url_required}
                  type="url"
                  spellCheck={false}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={ids.modelId}>
                  Model ID<span className="ml-1 text-destructive">*</span>
                </Label>
                <Input
                  id={ids.modelId}
                  value={state.modelId}
                  onChange={(e) => patch('modelId', e.target.value)}
                  placeholder="gpt-4o-mini"
                  required
                  list={`${ids.modelId}-suggestions`}
                  spellCheck={false}
                />
                {suggestedModels.length > 0 ? (
                  <datalist id={`${ids.modelId}-suggestions`}>
                    {suggestedModels.map((suggestion) => (
                      <option key={suggestion} value={suggestion} />
                    ))}
                  </datalist>
                ) : null}
              </div>
              <ApiKeyField
                id={ids.apiKey}
                isEdit={isEdit}
                last4={model?.api_key_last4 ?? null}
                replaceMode={state.replaceApiKey}
                value={state.apiKey}
                onReplaceModeChange={(next) => {
                  patch('replaceApiKey', next)
                  if (!next) patch('apiKey', '')
                }}
                onValueChange={(next) => patch('apiKey', next)}
              />
            </section>

            {/* Generation defaults — collapsible */}
            <section className="space-y-3">
              <button
                type="button"
                className="flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
                onClick={() => setAdvancedOpen((prev) => !prev)}
                aria-expanded={advancedOpen}
              >
                Generation defaults
                <ChevronDownIcon
                  className={cn(
                    'h-3 w-3 transition-transform',
                    advancedOpen ? 'rotate-180' : 'rotate-0'
                  )}
                  aria-hidden
                />
              </button>
              {advancedOpen ? (
                <div className="space-y-3">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label htmlFor={ids.temperature}>Temperature</Label>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {state.defaultTemperature.toFixed(1)}
                      </span>
                    </div>
                    <input
                      id={ids.temperature}
                      type="range"
                      min={0}
                      max={2}
                      step={0.1}
                      value={state.defaultTemperature}
                      onChange={(e) => patch('defaultTemperature', Number(e.target.value))}
                      className="w-full accent-primary"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={ids.maxTokens}>Max tokens</Label>
                    <Input
                      id={ids.maxTokens}
                      type="number"
                      min={1}
                      max={200000}
                      value={state.defaultMaxTokens}
                      onChange={(e) => patch('defaultMaxTokens', Number(e.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={ids.capabilities}>Capabilities (JSON)</Label>
                    <Textarea
                      id={ids.capabilities}
                      value={state.capabilitiesJson}
                      onChange={(e) => patch('capabilitiesJson', e.target.value)}
                      rows={4}
                      className="font-mono text-xs"
                      spellCheck={false}
                      aria-invalid={Boolean(capabilitiesError) || undefined}
                    />
                    {capabilitiesError ? (
                      <p className="text-xs text-destructive">{capabilitiesError}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Optional. e.g.{' '}
                        <code className="font-mono">{`{ "function_calling": true, "json_mode": true }`}</code>
                      </p>
                    )}
                  </div>
                </div>
              ) : null}
            </section>

            {/* Test connection */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Test connection
              </h3>
              <div className="flex flex-wrap items-center gap-3">
                {(() => {
                  // The plaintext test endpoint requires an API key in the request
                  // body. In edit mode, when the admin has not toggled "Replace API
                  // key", the form has no key to send — disable the button and tell
                  // the user how to test the saved key instead.
                  const testDisabledReason =
                    isEdit && !state.replaceApiKey
                      ? 'Toggle "Replace API key" to test with a new key, or use "Test" from the row menu to test the saved key.'
                      : null
                  const button = (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={handleTest}
                      disabled={testMutation.isPending || testDisabledReason !== null}
                      className="gap-1.5"
                    >
                      {testMutation.isPending ? (
                        <Loader2Icon className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      ) : (
                        <ZapIcon className="h-3.5 w-3.5" aria-hidden />
                      )}
                      {testMutation.isPending ? 'Testing…' : 'Test connection'}
                    </Button>
                  )
                  if (!testDisabledReason) return button
                  return (
                    <TooltipProvider delayDuration={150}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          {/*
                            biome-ignore lint/a11y/noNoninteractiveTabindex: the
                            wrapping span needs to be focusable so the tooltip can
                            announce the reason to keyboard users — the disabled
                            <button> inside swallows pointer/focus events.
                          */}
                          <span tabIndex={0} className="inline-flex">
                            {button}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs text-xs">
                          {testDisabledReason}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  )
                })()}
                {testResult ? (
                  <Badge
                    className={cn(
                      'gap-1 text-[11px]',
                      testResult.ok
                        ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                        : 'bg-destructive/15 text-destructive'
                    )}
                  >
                    {testResult.ok ? (
                      <CheckCircle2Icon className="h-3 w-3" aria-hidden />
                    ) : (
                      <AlertCircleIcon className="h-3 w-3" aria-hidden />
                    )}
                    {testResult.text}
                  </Badge>
                ) : null}
              </div>
              <p className="text-xs text-muted-foreground">
                Optional. Verifies the credentials and base URL without persisting the key. The
                plaintext key never leaves this request.
              </p>
            </section>
          </div>

          <footer className="mt-auto flex items-center justify-end gap-2 border-t border-border px-6 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : isEdit ? 'Save changes' : 'Create AI model'}
            </Button>
          </footer>
        </form>
      </SheetContent>
    </Sheet>
  )
}
