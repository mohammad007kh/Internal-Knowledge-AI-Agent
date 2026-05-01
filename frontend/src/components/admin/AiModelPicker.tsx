'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useAiModels } from '@/hooks/use-ai-models'
import { cn } from '@/lib/utils'
import type { AIModelPublic, TestConnectionStatus } from '@/types/ai-model'
import { AlertCircleIcon, CheckIcon, ChevronsUpDownIcon, CpuIcon, PlusIcon } from 'lucide-react'
import Link from 'next/link'
import { useMemo, useState } from 'react'

/**
 * Searchable AI Model picker — Combobox built on shadcn `Command` + `Popover`.
 *
 * Two-line rows:
 *  - Line 1: human name + provider Badge + tested-status dot
 *  - Line 2: model_id (mono, muted)
 *
 * Search filters across name, provider, model_id (cmdk handles it via the
 * `value` prop on each item).
 *
 * Capability filtering (design doc §11): incompatible models are shown
 * disabled with an explanatory tooltip. Sort: compatible first by ascending
 * `input_cost_per_1m`. The picker treats LLM and embedder as orthogonal —
 * cross-provider pairings render a soft hint (managed at the call site), but
 * are never blocked here.
 *
 * Empty state: zero AI Models → CTA linking to `/admin/ai-models?new=1`.
 */

export type CapabilityRequirement = 'function_calling' | 'vision' | 'json_mode' | 'streaming'

export interface StageRequirement {
  capabilities?: readonly CapabilityRequirement[]
  min_context_tokens?: number
}

interface AiModelPickerProps {
  /** Selected ai_model_id, or null if unset. */
  value: string | null
  /** Stage requirements — see STAGE_REQUIREMENTS in design doc §11. */
  requirement?: StageRequirement
  /** Optional placeholder when no value is selected. */
  placeholder?: string
  /** Disable the trigger. */
  disabled?: boolean
  onChange: (id: string) => void
  /** Optional id for label association on the trigger button. */
  id?: string
}

interface CompatibilityCheck {
  compatible: boolean
  /** Human-readable reasons for incompatibility, used in tooltips. */
  reasons: readonly string[]
}

const CAPABILITY_LABEL: Record<CapabilityRequirement, string> = {
  function_calling: 'function_calling',
  vision: 'vision',
  json_mode: 'json_mode',
  streaming: 'streaming',
}

function checkCompatibility(
  model: AIModelPublic,
  requirement: StageRequirement | undefined
): CompatibilityCheck {
  if (!requirement) return { compatible: true, reasons: [] }

  const reasons: string[] = []
  const required = requirement.capabilities ?? []
  for (const cap of required) {
    const supported = model.capabilities[cap]
    if (!supported) {
      reasons.push(`Requires ${CAPABILITY_LABEL[cap]} — \`${model.model_id}\` does not declare it.`)
    }
  }

  if (requirement.min_context_tokens) {
    const ctx = model.capabilities.max_context_tokens ?? 0
    if (ctx < requirement.min_context_tokens) {
      reasons.push(
        `Requires ≥ ${requirement.min_context_tokens.toLocaleString()} context tokens (\`${model.model_id}\` declares ${ctx.toLocaleString()}).`
      )
    }
  }

  return { compatible: reasons.length === 0, reasons }
}

const TEST_DOT_CLASS: Record<TestConnectionStatus, string> = {
  ok: 'bg-emerald-500',
  failed: 'bg-destructive',
  never: 'bg-muted-foreground/40',
}

function TestStatusDot({ status }: { status: TestConnectionStatus }) {
  const label =
    status === 'ok'
      ? 'Connection healthy'
      : status === 'failed'
        ? 'Last connection test failed'
        : 'Untested'
  return (
    <span
      className={cn('inline-block h-2 w-2 rounded-full', TEST_DOT_CLASS[status])}
      role="img"
      aria-label={label}
      title={label}
    />
  )
}

function searchKey(model: AIModelPublic): string {
  return `${model.name} ${model.provider} ${model.model_id}`.toLowerCase()
}

function ModelRow({ model }: { model: AIModelPublic }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
      <div className="flex items-center gap-2">
        <span className="truncate font-medium">{model.name}</span>
        <Badge variant="secondary" className="shrink-0 text-[10px] uppercase tracking-wide">
          {model.provider}
        </Badge>
        <TestStatusDot status={model.last_test_status} />
      </div>
      <span className="truncate font-mono text-xs text-muted-foreground">{model.model_id}</span>
    </div>
  )
}

export function AiModelPicker({
  value,
  requirement,
  placeholder,
  disabled,
  onChange,
  id,
}: AiModelPickerProps) {
  const [open, setOpen] = useState(false)
  // Pull the full list once — pickers are interactive enough to justify it.
  const { data, isLoading, isError } = useAiModels({ limit: 200 })

  const items = data?.items ?? []
  const selected = useMemo(() => items.find((item) => item.id === value) ?? null, [items, value])

  // Pre-compute compatibility, then sort (compatible first, by cost ascending).
  const sortedItems = useMemo(() => {
    const decorated = items.map((model) => ({
      model,
      compat: checkCompatibility(model, requirement),
    }))
    decorated.sort((a, b) => {
      if (a.compat.compatible !== b.compat.compatible) {
        return a.compat.compatible ? -1 : 1
      }
      const costA = a.model.capabilities.input_cost_per_1m ?? Number.POSITIVE_INFINITY
      const costB = b.model.capabilities.input_cost_per_1m ?? Number.POSITIVE_INFINITY
      if (costA !== costB) return costA - costB
      return a.model.name.localeCompare(b.model.name)
    })
    return decorated
  }, [items, requirement])

  const isEmpty = !isLoading && items.length === 0

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Select AI model"
          disabled={disabled}
          className="h-auto w-full justify-between gap-2 py-2 text-left font-normal"
        >
          {selected ? (
            <ModelRow model={selected} />
          ) : (
            <span className="flex items-center gap-2 text-muted-foreground">
              <CpuIcon className="h-4 w-4" aria-hidden />
              {placeholder ?? (isLoading ? 'Loading models…' : 'Select an AI model')}
            </span>
          )}
          <ChevronsUpDownIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[360px] p-0" align="start">
        {isEmpty ? (
          <div className="flex flex-col items-center gap-3 p-6 text-center">
            <CpuIcon className="h-8 w-8 text-muted-foreground" aria-hidden />
            <div className="space-y-1">
              <p className="text-sm font-medium">No AI models configured</p>
              <p className="text-xs text-muted-foreground">
                Add one to assign it to a pipeline stage.
              </p>
            </div>
            <Button asChild size="sm" className="gap-1.5">
              <Link href="/admin/ai-models?new=1">
                <PlusIcon className="h-3.5 w-3.5" aria-hidden />
                Configure first AI model
              </Link>
            </Button>
          </div>
        ) : (
          <Command shouldFilter>
            <CommandInput placeholder="Search models…" autoFocus />
            <CommandList>
              {isError ? (
                <div className="flex items-center gap-2 px-3 py-4 text-sm text-destructive">
                  <AlertCircleIcon className="h-4 w-4" aria-hidden />
                  Failed to load models.
                </div>
              ) : null}
              <CommandEmpty>No models match your search.</CommandEmpty>
              <CommandGroup>
                <TooltipProvider delayDuration={200}>
                  {sortedItems.map(({ model, compat }) => {
                    const disableItem = !compat.compatible
                    const itemBody = (
                      <CommandItem
                        key={model.id}
                        value={searchKey(model)}
                        disabled={disableItem}
                        onSelect={() => {
                          if (disableItem) return
                          onChange(model.id)
                          setOpen(false)
                        }}
                        className="items-start gap-3 py-2"
                      >
                        <CheckIcon
                          className={cn(
                            'mt-1 h-4 w-4 shrink-0',
                            value === model.id ? 'opacity-100' : 'opacity-0'
                          )}
                          aria-hidden
                        />
                        <ModelRow model={model} />
                        {disableItem ? (
                          <span className="sr-only">
                            {/* Reason text is duplicated here so screen-readers without
                                tooltip support still announce why the item is disabled. */}
                            {compat.reasons.join(' ')}
                          </span>
                        ) : null}
                      </CommandItem>
                    )

                    if (!disableItem) return itemBody

                    return (
                      <Tooltip key={model.id}>
                        <TooltipTrigger asChild>
                          {/*
                            Wrap in a focusable element so the tooltip fires for keyboard
                            users too — Radix's TooltipTrigger needs a focusable child to
                            attach focus listeners. role="option" + aria-disabled keeps
                            the AT semantics aligned with the underlying CommandItem.
                          */}
                          <span
                            tabIndex={0}
                            role="option"
                            aria-disabled="true"
                            aria-selected="false"
                            className="block cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
                          >
                            {itemBody}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-xs space-y-1">
                          {compat.reasons.map((reason) => (
                            <p key={reason} className="text-xs">
                              {reason}
                            </p>
                          ))}
                        </TooltipContent>
                      </Tooltip>
                    )
                  })}
                </TooltipProvider>
              </CommandGroup>
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  )
}
