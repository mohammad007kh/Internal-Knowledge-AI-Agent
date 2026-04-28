'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { Loader2Icon, RefreshCwIcon, SearchIcon } from 'lucide-react'

export type TypeGroup = 'all' | 'database' | 'file' | 'web' | 'integration'
export type StatusFilter = 'all' | 'pending' | 'syncing' | 'ready' | 'error' | 'disabled'

interface TypeChip {
  value: TypeGroup
  label: string
}

const TYPE_CHIPS: readonly TypeChip[] = [
  { value: 'all', label: 'All' },
  { value: 'file', label: 'Files' },
  { value: 'database', label: 'Database' },
  { value: 'web', label: 'Web' },
  { value: 'integration', label: 'Integration' },
] as const

interface SourcesToolbarProps {
  search: string
  onSearchChange: (value: string) => void
  typeFilter: TypeGroup
  onTypeFilterChange: (value: TypeGroup) => void
  statusFilter: StatusFilter
  onStatusFilterChange: (value: StatusFilter) => void
  totalCount: number
  syncCandidateCount: number
  onSyncAll: () => void
  isSyncingAll: boolean
}

/**
 * Toolbar for /admin/sources: search input + type filter chips + status select
 * + "Sync all" action.
 *
 * Filter chips use button styling instead of raw <Select> to keep the visual
 * weight closer to the rest of the admin (`/admin/users` tab pattern).
 */
export function SourcesToolbar({
  search,
  onSearchChange,
  typeFilter,
  onTypeFilterChange,
  statusFilter,
  onStatusFilterChange,
  totalCount,
  syncCandidateCount,
  onSyncAll,
  isSyncingAll,
}: SourcesToolbarProps) {
  const countLabel = `${totalCount} ${totalCount === 1 ? 'source' : 'sources'}`
  const canSyncAll = syncCandidateCount > 0 && !isSyncingAll

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative w-full sm:max-w-sm sm:flex-1">
          <SearchIcon
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search by name…"
            aria-label="Search sources"
            className="pl-9"
          />
        </div>

        <span className="hidden text-xs text-muted-foreground tabular-nums sm:inline">
          {countLabel}
        </span>

        <div className="flex items-center gap-2 sm:ml-auto">
          <Select
            value={statusFilter}
            onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}
          >
            <SelectTrigger
              className="h-9 flex-1 text-sm sm:w-[160px] sm:flex-none"
              aria-label="Filter by status"
            >
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="ready">Ready</SelectItem>
              <SelectItem value="syncing">Syncing</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="error">Error</SelectItem>
              <SelectItem value="disabled">Disabled</SelectItem>
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            size="sm"
            onClick={onSyncAll}
            disabled={!canSyncAll}
            className="shrink-0 gap-1.5"
            aria-label={
              syncCandidateCount > 0
                ? `Sync all ${syncCandidateCount} eligible sources`
                : 'No sources eligible for sync'
            }
          >
            {isSyncingAll ? (
              <Loader2Icon className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <RefreshCwIcon className="h-4 w-4" aria-hidden />
            )}
            <span>Sync all</span>
          </Button>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums sm:hidden">{countLabel}</span>
      </div>

      <div
        className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
        role="group"
        aria-label="Filter by type"
      >
        {TYPE_CHIPS.map((chip) => {
          const isActive = chip.value === typeFilter
          return (
            <button
              key={chip.value}
              type="button"
              onClick={() => onTypeFilterChange(chip.value)}
              aria-pressed={isActive}
              className={cn(
                'inline-flex h-8 shrink-0 items-center rounded-full border px-3 text-xs font-medium transition-colors sm:h-7',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                isActive
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              {chip.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
