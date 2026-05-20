'use client'

import type {
  ActiveChip,
  StageFilterState,
} from '@/app/(admin)/admin/llm-settings/_components/useStageFilters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { FilterIcon, SearchIcon, XIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

interface StagesToolbarProps {
  state: StageFilterState
  onChange: (updater: (prev: StageFilterState) => StageFilterState) => void
  availableProviders: readonly string[]
  activeChips: readonly ActiveChip[]
  onClearAll: () => void
  totalCount: number
  filteredCount: number
}

const STATUS_OPTIONS: ReadonlyArray<{
  value: StageFilterState['status']
  label: string
}> = [
  { value: 'all', label: 'All' },
  { value: 'configured', label: 'Configured' },
  { value: 'not_configured', label: 'Not configured' },
]

const CUSTOM_PROMPT_OPTIONS: ReadonlyArray<{
  value: StageFilterState['customPrompt']
  label: string
}> = [
  { value: 'any', label: 'Any' },
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
]

/**
 * Toolbar for /admin/llm-settings: search + provider/status/custom-prompt
 * filters + active chip strip + count.
 *
 * Strictly presentational — owns no filter state. The page's
 * `useStageFilters` hook owns state and URL sync.
 */
export function StagesToolbar({
  state,
  onChange,
  availableProviders,
  activeChips,
  onClearAll,
  totalCount,
  filteredCount,
}: StagesToolbarProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  // Page-scoped `/` shortcut: focus the search input unless the user is
  // already typing somewhere (input/textarea/contentEditable).
  useEffect(() => {
    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false
      const tag = target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
      if (target.isContentEditable) return true
      return false
    }

    function handler(event: KeyboardEvent) {
      if (event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey) {
        if (isEditableTarget(event.target)) return
        event.preventDefault()
        inputRef.current?.focus()
        return
      }
      if (event.key === 'Escape' && document.activeElement === inputRef.current) {
        if (state.search !== '') {
          onChange((prev) => ({ ...prev, search: '' }))
        }
        inputRef.current?.blur()
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onChange, state.search])

  const filterCount =
    state.providers.length +
    (state.status !== 'all' ? 1 : 0) +
    (state.customPrompt !== 'any' ? 1 : 0)

  function toggleProvider(provider: string) {
    onChange((prev) => {
      const has = prev.providers.includes(provider)
      const next = has
        ? prev.providers.filter((p) => p !== provider)
        : [...prev.providers, provider]
      return { ...prev, providers: next }
    })
  }

  function setStatus(value: StageFilterState['status']) {
    onChange((prev) => ({ ...prev, status: value }))
  }

  function setCustomPrompt(value: StageFilterState['customPrompt']) {
    onChange((prev) => ({ ...prev, customPrompt: value }))
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative w-full sm:max-w-md sm:flex-1">
          <SearchIcon
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            ref={inputRef}
            type="search"
            value={state.search}
            onChange={(e) => onChange((prev) => ({ ...prev, search: e.target.value }))}
            placeholder="Search stages, models, providers…"
            aria-label="Search stages"
            className="pl-9 pr-9"
          />
          {state.search ? (
            <button
              type="button"
              onClick={() => {
                onChange((prev) => ({ ...prev, search: '' }))
                inputRef.current?.focus()
              }}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              <XIcon className="h-3.5 w-3.5" aria-hidden />
            </button>
          ) : null}
        </div>

        {/* Desktop: inline filters */}
        <div className="hidden flex-wrap items-center gap-3 sm:flex sm:ml-auto">
          <ProviderPills
            providers={availableProviders}
            selected={state.providers}
            onToggle={toggleProvider}
          />
          <SegmentedControl
            label="Status"
            options={STATUS_OPTIONS}
            value={state.status}
            onChange={setStatus}
          />
          <SegmentedControl
            label="Custom prompt"
            options={CUSTOM_PROMPT_OPTIONS}
            value={state.customPrompt}
            onChange={setCustomPrompt}
          />
        </div>

        {/* Mobile: filters open in a Sheet */}
        <div className="sm:hidden">
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <FilterIcon className="h-4 w-4" aria-hidden />
                Filters
                {filterCount > 0 ? (
                  <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                    {filterCount}
                  </Badge>
                ) : null}
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="flex w-full max-w-sm flex-col gap-4 p-4">
              <SheetTitle>Filters</SheetTitle>
              <div className="flex flex-1 flex-col gap-5 overflow-y-auto">
                <FilterGroup label="Provider">
                  <ProviderPills
                    providers={availableProviders}
                    selected={state.providers}
                    onToggle={toggleProvider}
                    wrap
                  />
                </FilterGroup>
                <FilterGroup label="Status">
                  <SegmentedControl
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={state.status}
                    onChange={setStatus}
                    hideLabel
                  />
                </FilterGroup>
                <FilterGroup label="Custom prompt">
                  <SegmentedControl
                    label="Custom prompt"
                    options={CUSTOM_PROMPT_OPTIONS}
                    value={state.customPrompt}
                    onChange={setCustomPrompt}
                    hideLabel
                  />
                </FilterGroup>
              </div>
              <div className="flex items-center justify-between gap-2 border-t pt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onClearAll()
                  }}
                >
                  Clear
                </Button>
                <SheetClose asChild>
                  <Button size="sm">Apply</Button>
                </SheetClose>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground tabular-nums">
          Showing {filteredCount} of {totalCount} stages
        </span>
        {activeChips.length > 0 ? (
          <>
            <span aria-hidden className="text-xs text-muted-foreground">
              ·
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              {activeChips.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  onClick={chip.remove}
                  className="inline-flex h-7 items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 text-xs text-foreground hover:bg-muted"
                >
                  <span>{chip.label}</span>
                  <XIcon className="h-3 w-3 text-muted-foreground" aria-hidden />
                </button>
              ))}
              <button
                type="button"
                onClick={onClearAll}
                className="text-xs font-medium text-primary hover:underline"
              >
                Clear all
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}

interface ProviderPillsProps {
  providers: readonly string[]
  selected: readonly string[]
  onToggle: (provider: string) => void
  wrap?: boolean
}

function ProviderPills({ providers, selected, onToggle, wrap }: ProviderPillsProps) {
  if (providers.length === 0) return null
  return (
    <div
      role="group"
      aria-label="Filter by provider"
      className={cn(
        '-mx-1 flex items-center gap-1.5 px-1',
        wrap ? 'flex-wrap' : 'overflow-x-auto'
      )}
    >
      {providers.map((provider) => {
        const isActive = selected.includes(provider)
        return (
          <button
            key={provider}
            type="button"
            onClick={() => onToggle(provider)}
            aria-pressed={isActive}
            className={cn(
              'inline-flex h-7 shrink-0 items-center rounded-full border px-3 text-xs font-medium uppercase tracking-wide transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              isActive
                ? 'border-primary/40 bg-primary/10 text-primary'
                : 'border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
            )}
          >
            {provider}
          </button>
        )
      })}
    </div>
  )
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  )
}
