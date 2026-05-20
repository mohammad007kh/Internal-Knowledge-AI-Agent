'use client'

import type {
  ActiveChip,
  AuditLogFilterState,
} from '@/app/(admin)/admin/audit-log/_components/useAuditLogFilters'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SearchIcon, XIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'

interface AuditLogToolbarProps {
  state: AuditLogFilterState
  onChange: (
    updater: (prev: AuditLogFilterState) => AuditLogFilterState
  ) => void
  activeChips: readonly ActiveChip[]
  onClearAll: () => void
  totalCount: number
  filteredCount: number
}

/**
 * Predefined `action` values that the backend writes today. Keeping this
 * list narrow on the UI side (vs free-text input) prevents typos and gives
 * the admin a discoverable menu of what's loggable. New actions added on
 * the backend should be reflected here — falling out of sync just means
 * the dropdown can't filter them, the table will still display them.
 */
const ACTION_OPTIONS = [
  { value: 'login_success', label: 'login_success' },
  { value: 'login_failure', label: 'login_failure' },
  { value: 'user.invite', label: 'user.invite' },
  { value: 'user.role_change', label: 'user.role_change' },
  { value: 'user.deactivate', label: 'user.deactivate' },
  { value: 'source.create', label: 'source.create' },
  { value: 'source.update', label: 'source.update' },
  { value: 'source.delete', label: 'source.delete' },
  { value: 'source.credentials_update', label: 'source.credentials_update' },
  // Resource-prefixed values must match exactly what the backend writes —
  // bare verbs like 'create' would send `?action=create` and miss every
  // row whose `action` is stored as `ai_model.create`.
  { value: 'ai_model.create', label: 'ai_model.create' },
  { value: 'ai_model.update', label: 'ai_model.update' },
  { value: 'ai_model.delete', label: 'ai_model.delete' },
  { value: 'ai_model.test', label: 'ai_model.test' },
  { value: 'embedder.create', label: 'embedder.create' },
  { value: 'embedder.update', label: 'embedder.update' },
  { value: 'embedder.delete', label: 'embedder.delete' },
  { value: 'embedder.test', label: 'embedder.test' },
  { value: 'llm_setting.update', label: 'llm_setting.update' },
] as const

const RESOURCE_TYPE_OPTIONS = [
  { value: 'user', label: 'user' },
  { value: 'source', label: 'source' },
  { value: 'ai_model', label: 'ai_model' },
  { value: 'embedder', label: 'embedder' },
  { value: 'llm_configuration', label: 'llm_configuration' },
  { value: 'guardrail', label: 'guardrail' },
  { value: 'policy', label: 'policy' },
] as const

// shadcn `Select` does not allow an empty-string item value (Radix throws),
// so we use a non-empty sentinel internally and translate at the boundary.
const ALL_SENTINEL = '__all__'

export function AuditLogToolbar({
  state,
  onChange,
  activeChips,
  onClearAll,
  totalCount,
  filteredCount,
}: AuditLogToolbarProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Page-scoped `/` shortcut: focus the search input unless the user is
  // already typing somewhere else.
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
          onChange((prev) => ({ ...prev, search: '', page: 1 }))
        }
        inputRef.current?.blur()
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onChange, state.search])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center">
        <div className="relative w-full md:max-w-xs">
          <SearchIcon
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            ref={inputRef}
            type="search"
            value={state.search}
            onChange={(e) =>
              onChange((prev) => ({ ...prev, search: e.target.value, page: 1 }))
            }
            placeholder="Search metadata…"
            aria-label="Search metadata"
            className="pl-9 pr-9"
          />
          {state.search ? (
            <button
              type="button"
              onClick={() => {
                onChange((prev) => ({ ...prev, search: '', page: 1 }))
                inputRef.current?.focus()
              }}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              <XIcon className="h-3.5 w-3.5" aria-hidden />
            </button>
          ) : null}
        </div>

        <Select
          value={state.action === '' ? ALL_SENTINEL : state.action}
          onValueChange={(value) =>
            onChange((prev) => ({
              ...prev,
              action: value === ALL_SENTINEL ? '' : value,
              page: 1,
            }))
          }
        >
          <SelectTrigger className="w-full md:w-[200px]" aria-label="Filter by action">
            <SelectValue placeholder="All actions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SENTINEL}>All actions</SelectItem>
            {ACTION_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={state.resourceType === '' ? ALL_SENTINEL : state.resourceType}
          onValueChange={(value) =>
            onChange((prev) => ({
              ...prev,
              resourceType: value === ALL_SENTINEL ? '' : value,
              page: 1,
            }))
          }
        >
          <SelectTrigger
            className="w-full md:w-[180px]"
            aria-label="Filter by resource type"
          >
            <SelectValue placeholder="All resources" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SENTINEL}>All resources</SelectItem>
            {RESOURCE_TYPE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={state.from}
            onChange={(e) =>
              onChange((prev) => ({ ...prev, from: e.target.value, page: 1 }))
            }
            aria-label="From date"
            className="w-[160px]"
          />
          <span className="text-xs text-muted-foreground" aria-hidden>
            →
          </span>
          <Input
            type="date"
            value={state.to}
            onChange={(e) =>
              onChange((prev) => ({ ...prev, to: e.target.value, page: 1 }))
            }
            aria-label="To date"
            className="w-[160px]"
          />
        </div>

        <Input
          value={state.adminUserId}
          onChange={(e) =>
            onChange((prev) => ({ ...prev, adminUserId: e.target.value, page: 1 }))
          }
          placeholder="Admin user UUID…"
          aria-label="Filter by admin user UUID"
          className="w-full md:w-[280px]"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground tabular-nums">
          Showing {filteredCount} of {totalCount} entries
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
              <Button
                variant="ghost"
                size="sm"
                onClick={onClearAll}
                className="h-7 px-2 text-xs"
              >
                Clear all
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
