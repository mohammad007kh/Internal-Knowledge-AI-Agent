'use client'

import { ApiKeyField } from '@/components/admin/ApiKeyField'
import { ProviderSelect } from '@/components/admin/ProviderSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import {
  useCreateEmbedder,
  useTestEmbedderConnection,
  useUpdateEmbedder,
} from '@/hooks/use-embedders'
import { useProvider } from '@/hooks/use-providers'
import { cn } from '@/lib/utils'
import type { EmbedderCreateRequest, EmbedderPublic, EmbedderUpdateRequest } from '@/types/embedder'
import type { ProviderSpec } from '@/types/provider'
import { AlertCircleIcon, CheckCircle2Icon, Loader2Icon, ZapIcon } from 'lucide-react'
import { useEffect, useId, useMemo, useState } from 'react'
import { toast } from 'sonner'

/**
 * Embedder create/edit form, presented in a `Sheet`.
 *
 * Important constraints:
 *  - `dimensions` is **read-only on edit** (per design doc §7).
 *  - v1 only allows activating embedders with `dimensions == 1536` — that's
 *    enforced server-side, but we surface a warning here when the user picks
 *    a non-1536 model so they aren't surprised at activation time.
 */

interface EmbedderFormSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  embedder: EmbedderPublic | null
}

interface FormState {
  name: string
  providerKey: string | null
  baseUrl: string
  modelId: string
  apiKey: string
  replaceApiKey: boolean
  dimensions: number
  maxInputTokens: string
}

const EMPTY_FORM: FormState = {
  name: '',
  providerKey: null,
  baseUrl: '',
  modelId: '',
  apiKey: '',
  replaceApiKey: false,
  dimensions: 1536,
  maxInputTokens: '',
}

const V1_ACTIVATABLE_DIMENSIONS = 1536

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}

export function EmbedderFormSheet({ open, onOpenChange, embedder }: EmbedderFormSheetProps) {
  const isEdit = Boolean(embedder)
  const formId = useId()
  const createMutation = useCreateEmbedder()
  const updateMutation = useUpdateEmbedder()
  const testMutation = useTestEmbedderConnection()

  const [state, setState] = useState<FormState>(EMPTY_FORM)
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  const provider = useProvider(state.providerKey)
  const suggestedEmbedders = useMemo(() => provider?.embedder_models ?? [], [provider])

  useEffect(() => {
    if (!open) return
    if (embedder) {
      setState({
        name: embedder.name,
        providerKey: embedder.provider,
        baseUrl: embedder.base_url ?? '',
        modelId: embedder.model_id,
        apiKey: '',
        replaceApiKey: false,
        dimensions: embedder.dimensions,
        maxInputTokens: embedder.max_input_tokens === null ? '' : String(embedder.max_input_tokens),
      })
    } else {
      setState(EMPTY_FORM)
    }
    setTestResult(null)
  }, [open, embedder])

  function patch<K extends keyof FormState>(key: K, value: FormState[K]) {
    setState((prev) => ({ ...prev, [key]: value }))
  }

  function handleProviderChange(next: ProviderSpec) {
    setState((prev) => {
      const firstSuggestion = next.embedder_models[0]
      return {
        ...prev,
        providerKey: next.key,
        baseUrl: prev.baseUrl === '' ? (next.default_base_url ?? '') : prev.baseUrl,
        modelId: prev.modelId === '' ? (firstSuggestion?.model_id ?? '') : prev.modelId,
        // Pre-fill dimensions from the first suggestion when creating.
        dimensions:
          isEdit || !firstSuggestion?.dimensions ? prev.dimensions : firstSuggestion.dimensions,
      }
    })
  }

  function handleModelIdChange(next: string) {
    setState((prev) => {
      // Auto-fill dimensions when the user picks a known suggestion (only on create).
      if (!isEdit) {
        const match = suggestedEmbedders.find((m) => m.model_id === next)
        if (match?.dimensions) {
          return { ...prev, modelId: next, dimensions: match.dimensions }
        }
      }
      return { ...prev, modelId: next }
    })
  }

  function buildCreatePayload(): EmbedderCreateRequest | null {
    if (!state.providerKey) {
      toast.error('Pick a provider first.')
      return null
    }
    if (!state.apiKey) {
      toast.error('API key is required.')
      return null
    }
    const dims = Number(state.dimensions)
    if (!Number.isFinite(dims) || dims < 64 || dims > 4096) {
      toast.error('Dimensions must be between 64 and 4096.')
      return null
    }
    const maxTokens = state.maxInputTokens === '' ? undefined : Number(state.maxInputTokens)
    if (maxTokens !== undefined && (!Number.isFinite(maxTokens) || maxTokens < 1)) {
      toast.error('Max input tokens must be a positive integer.')
      return null
    }

    return {
      name: state.name.trim(),
      provider: state.providerKey,
      model_id: state.modelId.trim(),
      api_key: state.apiKey,
      dimensions: dims,
      base_url: state.baseUrl.trim() || null,
      max_input_tokens: maxTokens ?? null,
    }
  }

  function buildUpdatePayload(): EmbedderUpdateRequest | null {
    if (!state.providerKey) {
      toast.error('Pick a provider first.')
      return null
    }
    const maxTokens = state.maxInputTokens === '' ? null : Number(state.maxInputTokens)
    if (maxTokens !== null && (!Number.isFinite(maxTokens) || maxTokens < 1)) {
      toast.error('Max input tokens must be a positive integer.')
      return null
    }

    const payload: EmbedderUpdateRequest = {
      name: state.name.trim(),
      provider: state.providerKey,
      model_id: state.modelId.trim(),
      base_url: state.baseUrl.trim() || null,
      max_input_tokens: maxTokens,
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
    if (isEdit && embedder) {
      const payload = buildUpdatePayload()
      if (!payload) return
      updateMutation.mutate(
        { id: embedder.id, body: payload },
        {
          onSuccess: () => {
            toast.success('Embedder updated')
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
        toast.success('Embedder created')
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
    const dims = Number(state.dimensions)
    if (!Number.isFinite(dims) || dims < 64 || dims > 4096) {
      toast.error('Dimensions must be set to a valid number first.')
      return
    }

    setTestResult(null)
    testMutation.mutate(
      {
        provider: state.providerKey,
        model_id: state.modelId.trim(),
        api_key: state.apiKey,
        dimensions: dims,
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
  const dimensionsAreActivatable = Number(state.dimensions) === V1_ACTIVATABLE_DIMENSIONS

  const ids = {
    name: `${formId}-name`,
    provider: `${formId}-provider`,
    baseUrl: `${formId}-base-url`,
    modelId: `${formId}-model-id`,
    apiKey: `${formId}-api-key`,
    dimensions: `${formId}-dimensions`,
    maxTokens: `${formId}-max-tokens`,
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full max-w-full flex-col overflow-hidden p-0 sm:max-w-xl"
      >
        <header className="border-b border-border px-4 py-4 sm:px-6">
          <SheetTitle>{isEdit ? `Edit ${embedder?.name}` : 'New embedder'}</SheetTitle>
          <p className="mt-1 pr-8 text-sm text-muted-foreground">
            Embedder endpoint records. Activating one triggers a re-embed batch job.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col overflow-y-auto"
          autoComplete="off"
        >
          <div className="space-y-6 px-4 py-5 sm:px-6">
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
                  placeholder="OpenAI 3-Small"
                  required
                  maxLength={150}
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
                  kind="embedder"
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
                  onChange={(e) => handleModelIdChange(e.target.value)}
                  placeholder="text-embedding-3-small"
                  required
                  list={`${ids.modelId}-suggestions`}
                  spellCheck={false}
                />
                {suggestedEmbedders.length > 0 ? (
                  <datalist id={`${ids.modelId}-suggestions`}>
                    {suggestedEmbedders.map((suggestion) => (
                      <option key={suggestion.model_id} value={suggestion.model_id} />
                    ))}
                  </datalist>
                ) : null}
              </div>
              <ApiKeyField
                id={ids.apiKey}
                isEdit={isEdit}
                last4={embedder?.api_key_last4 ?? null}
                replaceMode={state.replaceApiKey}
                value={state.apiKey}
                onReplaceModeChange={(next) => {
                  patch('replaceApiKey', next)
                  if (!next) patch('apiKey', '')
                }}
                onValueChange={(next) => patch('apiKey', next)}
              />
            </section>

            {/* Embedder properties */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Embedder properties
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor={ids.dimensions}>
                    Dimensions<span className="ml-1 text-destructive">*</span>
                  </Label>
                  <Input
                    id={ids.dimensions}
                    type="number"
                    min={64}
                    max={4096}
                    value={state.dimensions}
                    disabled={isEdit}
                    readOnly={isEdit}
                    onChange={(e) => patch('dimensions', Number(e.target.value))}
                    aria-describedby={`${ids.dimensions}-help`}
                  />
                  <p id={`${ids.dimensions}-help`} className="text-xs text-muted-foreground">
                    {isEdit
                      ? 'Read-only. Dimensions are immutable once chunks reference this embedder.'
                      : 'Must match pgvector column. v1 invariant: only 1536-dim embedders can be activated.'}
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor={ids.maxTokens}>Max input tokens</Label>
                  <Input
                    id={ids.maxTokens}
                    type="number"
                    min={1}
                    value={state.maxInputTokens}
                    onChange={(e) => patch('maxInputTokens', e.target.value)}
                    placeholder="8192"
                  />
                  <p className="text-xs text-muted-foreground">
                    Optional. Used for chunk-size sanity checks.
                  </p>
                </div>
              </div>
              {!dimensionsAreActivatable ? (
                <div
                  className={cn(
                    'rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs',
                    'text-amber-900 dark:text-amber-200'
                  )}
                  role="status"
                >
                  <strong>Heads up:</strong> v1 only activates 1536-dim embedders. This embedder can
                  be saved but cannot be made active until v1.1 ships per-dim partitioned chunk
                  storage.
                </div>
              ) : null}
            </section>

            {/* Test connection */}
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Test connection
              </h3>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleTest}
                  disabled={testMutation.isPending}
                  className="gap-1.5"
                >
                  {testMutation.isPending ? (
                    <Loader2Icon className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <ZapIcon className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {testMutation.isPending ? 'Testing…' : 'Test connection'}
                </Button>
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
            </section>
          </div>

          <footer className="mt-auto flex flex-col-reverse items-stretch gap-2 border-t border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-end sm:px-6">
            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => onOpenChange(false)}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button type="submit" className="w-full sm:w-auto" disabled={isSaving}>
              {isSaving ? 'Saving…' : isEdit ? 'Save changes' : 'Create embedder'}
            </Button>
          </footer>
        </form>
      </SheetContent>
    </Sheet>
  )
}
