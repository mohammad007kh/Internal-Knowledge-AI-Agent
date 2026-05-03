'use client'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useProviders } from '@/hooks/use-providers'
import type { ProviderKind, ProviderSpec } from '@/types/provider'

/**
 * Provider dropdown used by AI Model and Embedder create/edit forms.
 *
 * On change, the parent receives the full `ProviderSpec` so it can populate
 * default base_url and suggested model IDs (per design doc §5).
 */

interface ProviderSelectProps {
  /** Selected provider key. */
  value: string | null
  /** Filter providers by capability. */
  kind: ProviderKind
  /** Disable the trigger (e.g. while saving). */
  disabled?: boolean
  onChange: (provider: ProviderSpec) => void
  /** Optional id for label association. */
  id?: string
}

/**
 * For embedders, hide providers that explicitly do not offer a native
 * embedder (e.g. Anthropic). They can still be reached via openai-compatible.
 *
 * Both `llm_models` and `embedder_models` are normalised to `[]` defensively
 * so a partially-populated payload from an older backend cannot crash the
 * picker (see /admin/embedders regression).
 */
function filterProviders(
  providers: readonly ProviderSpec[] | undefined,
  kind: ProviderKind
): readonly ProviderSpec[] {
  const list = providers ?? []
  if (kind === 'embedder') {
    return list.filter((p) => !p.embedder_unsupported && (p.embedder_models ?? []).length > 0)
  }
  return list.filter((p) => (p.llm_models ?? []).length > 0 || p.key === 'openai-compatible')
}

export function ProviderSelect({ value, kind, disabled, onChange, id }: ProviderSelectProps) {
  const { data, isLoading } = useProviders()
  const providers = filterProviders(data?.providers, kind)

  function handleChange(nextKey: string) {
    const provider = providers.find((p) => p.key === nextKey)
    if (provider) onChange(provider)
  }

  return (
    <Select
      value={value ?? undefined}
      onValueChange={handleChange}
      disabled={disabled || isLoading}
    >
      <SelectTrigger id={id} aria-label="Provider">
        <SelectValue placeholder={isLoading ? 'Loading providers…' : 'Select a provider'} />
      </SelectTrigger>
      <SelectContent>
        {providers.map((provider) => (
          <SelectItem key={provider.key} value={provider.key}>
            <div className="flex flex-col">
              <span>{provider.display}</span>
              {provider.default_base_url ? (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {provider.default_base_url}
                </span>
              ) : null}
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
