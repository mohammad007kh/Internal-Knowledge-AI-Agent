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
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative max-w-sm flex-1">
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

        <span className="text-xs text-muted-foreground tabular-nums">{countLabel}</span>

        <div className="ml-auto flex items-center gap-2">
          <Select
            value={statusFilter}
            onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}
          >
            <SelectTrigger className="h-9 w-[160px] text-sm" aria-label="Filter by status">
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
            className="gap-1.5"
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
            Sync all
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by type">
        {TYPE_CHIPS.map((chip) => {
          const isActive = chip.value === typeFilter
          return (
            <button
              key={chip.value}
              type="button"
              onClick={() => onTypeFilterChange(chip.value)}
              aria-pressed={isActive}
              className={cn(
                'inline-flex h-7 items-center rounded-full border px-3 text-xs font-medium transition-colors',
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
