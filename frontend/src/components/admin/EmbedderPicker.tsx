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
import { useEmbedders } from '@/hooks/use-embedders'
import { cn } from '@/lib/utils'
import type { EmbedderPublic } from '@/types/embedder'
import { AlertCircleIcon, CheckIcon, ChevronsUpDownIcon, LayersIcon, LockIcon } from 'lucide-react'
import Link from 'next/link'
import { useMemo, useState } from 'react'

/**
 * Embedder picker — searchable select grouped by provider.
 *
 * v1 lock: the picker is locked to the active embedder per design doc §6.1.
 * The single-active invariant is enforced server-side; the UI surfaces this
 * as a read-only state with explanatory copy and a link to
 * `/admin/embedders` for switching.
 *
 * Pass ``locked`` to opt into the lock-display state. When ``locked`` is
 * false (admin embedder management screen), the picker behaves like a
 * normal combobox.
 */

interface EmbedderPickerProps {
  /** Selected embedder_id, or null. */
  value: string | null
  /**
   * Locked mode (v1 default for source forms): show the active embedder
   * read-only with explanatory text linking to /admin/embedders.
   */
  locked?: boolean
  disabled?: boolean
  onChange: (id: string) => void
  /** Optional id for label association. */
  id?: string
}

function searchKey(embedder: EmbedderPublic): string {
  return `${embedder.name} ${embedder.provider} ${embedder.model_id}`.toLowerCase()
}

function EmbedderRow({ embedder }: { embedder: EmbedderPublic }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
      <div className="flex items-center gap-2">
        <span className="truncate font-medium">{embedder.name}</span>
        <Badge variant="secondary" className="shrink-0 text-[10px] uppercase tracking-wide">
          {embedder.provider}
        </Badge>
        {embedder.is_active ? (
          <Badge className="shrink-0 bg-emerald-500/15 text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
            Active
          </Badge>
        ) : null}
      </div>
      <span className="truncate font-mono text-xs text-muted-foreground">
        {embedder.model_id} · {embedder.dimensions} dims
      </span>
    </div>
  )
}

interface GroupedEmbedders {
  provider: string
  items: readonly EmbedderPublic[]
}

function groupByProvider(items: readonly EmbedderPublic[]): readonly GroupedEmbedders[] {
  const map = new Map<string, EmbedderPublic[]>()
  for (const item of items) {
    const list = map.get(item.provider)
    if (list) {
      list.push(item)
    } else {
      map.set(item.provider, [item])
    }
  }
  const groups: GroupedEmbedders[] = []
  for (const [provider, group] of map.entries()) {
    group.sort((a, b) => {
      if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    groups.push({ provider, items: group })
  }
  groups.sort((a, b) => a.provider.localeCompare(b.provider))
  return groups
}

export function EmbedderPicker({ value, locked, disabled, onChange, id }: EmbedderPickerProps) {
  const [open, setOpen] = useState(false)
  const { data, isLoading, isError } = useEmbedders({ limit: 200 })

  const items = data?.items ?? []
  const active = useMemo(() => items.find((e) => e.is_active) ?? null, [items])
  const selected = useMemo(() => {
    if (locked) return active
    return items.find((item) => item.id === value) ?? null
  }, [items, value, locked, active])

  const groups = useMemo(() => groupByProvider(items), [items])

  // Locked mode renders a read-only display with explanatory text. The
  // parent form should still submit the active embedder's id via onChange
  // when defaulting.
  if (locked) {
    return (
      <div className="space-y-2">
        <div
          id={id}
          className={cn(
            'flex h-auto min-h-10 w-full items-center gap-3 rounded-md border border-input bg-muted/30 px-3 py-2 text-sm'
          )}
          aria-readonly
        >
          <LockIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
          {selected ? (
            <EmbedderRow embedder={selected} />
          ) : (
            <span className="text-muted-foreground">
              {isLoading ? 'Loading active embedder…' : 'No active embedder configured'}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Embedder is set to the deployment&apos;s active embedder. Switch globally on{' '}
          <Link href="/admin/embedders" className="font-medium text-primary hover:underline">
            /admin/embedders
          </Link>
          .
        </p>
      </div>
    )
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Select embedder"
          disabled={disabled}
          className="h-auto w-full justify-between gap-2 py-2 text-left font-normal"
        >
          {selected ? (
            <EmbedderRow embedder={selected} />
          ) : (
            <span className="flex items-center gap-2 text-muted-foreground">
              <LayersIcon className="h-4 w-4" aria-hidden />
              {isLoading ? 'Loading embedders…' : 'Select an embedder'}
            </span>
          )}
          <ChevronsUpDownIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[360px] p-0" align="start">
        <Command shouldFilter>
          <CommandInput placeholder="Search embedders…" autoFocus />
          <CommandList>
            {isError ? (
              <div className="flex items-center gap-2 px-3 py-4 text-sm text-destructive">
                <AlertCircleIcon className="h-4 w-4" aria-hidden />
                Failed to load embedders.
              </div>
            ) : null}
            <CommandEmpty>No embedders match your search.</CommandEmpty>
            {groups.map(({ provider, items: groupItems }) => (
              <CommandGroup key={provider} heading={provider}>
                {groupItems.map((embedder) => (
                  <CommandItem
                    key={embedder.id}
                    value={searchKey(embedder)}
                    onSelect={() => {
                      onChange(embedder.id)
                      setOpen(false)
                    }}
                    className="items-start gap-3 py-2"
                  >
                    <CheckIcon
                      className={cn(
                        'mt-1 h-4 w-4 shrink-0',
                        value === embedder.id ? 'opacity-100' : 'opacity-0'
                      )}
                      aria-hidden
                    />
                    <EmbedderRow embedder={embedder} />
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
