'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import { CheckIcon, ChevronDownIcon, DatabaseIcon, SearchIcon } from 'lucide-react'
import { useCallback, useState } from 'react'

export interface SourceSummary {
  id: string
  name: string
  type: string
  document_count: number
}

interface SourceResponse {
  items: SourceSummary[]
  total: number
}

interface SourceSelectorProps {
  selectedIds: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}

async function fetchSources(): Promise<SourceResponse> {
  const res = await apiClient.get('/sources?limit=100&status=ready')
  return res.data
}

interface SourceListBoxProps {
  filtered: SourceSummary[]
  selectedIds: string[]
  toggle: (id: string) => void
}

function SourceListBox({ filtered, selectedIds, toggle }: SourceListBoxProps) {
  const box = (
    <div role="listbox" aria-multiselectable="true" className="py-1" tabIndex={-1}>
      {filtered.map((source) => {
        const isSelected = selectedIds.includes(source.id)
        return (
          <SourceListItem key={source.id} source={source} isSelected={isSelected} toggle={toggle} />
        )
      })}
    </div>
  )
  return box
}

interface SourceListItemProps {
  source: SourceSummary
  isSelected: boolean
  toggle: (id: string) => void
}

function SourceListItem({ source, isSelected, toggle }: SourceListItemProps) {
  const item = (
    <div
      role="option"
      aria-selected={isSelected}
      tabIndex={0}
      className={cn(
        'flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-accent',
        isSelected && 'bg-accent/50'
      )}
      onClick={() => toggle(source.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          toggle(source.id)
        }
      }}
    >
      <div
        className={cn(
          'flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border',
          isSelected && 'border-primary bg-primary'
        )}
        aria-hidden="true"
      >
        {isSelected && <CheckIcon className="h-3 w-3 text-primary-foreground" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{source.name}</p>
        <p className="text-xs text-muted-foreground">
          {source.type} · {source.document_count} docs
        </p>
      </div>
    </div>
  )
  return item
}

export function SourceSelector({ selectedIds, onChange, disabled }: SourceSelectorProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const { data } = useQuery({
    queryKey: ['sources-list'],
    queryFn: fetchSources,
    staleTime: 60_000,
    enabled: open,
  })

  const sources: SourceSummary[] = data?.items ?? []
  const filtered = sources.filter((s) => s.name.toLowerCase().includes(search.toLowerCase()))

  const toggle = useCallback(
    (id: string) => {
      if (selectedIds.includes(id)) {
        onChange(selectedIds.filter((x) => x !== id))
      } else {
        onChange([...selectedIds, id])
      }
    },
    [selectedIds, onChange]
  )

  const selectedCount = selectedIds.length

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 rounded-full text-xs"
          disabled={disabled}
          aria-label={
            selectedCount > 0
              ? `${selectedCount} source${selectedCount !== 1 ? 's' : ''} selected`
              : 'All sources'
          }
        >
          <DatabaseIcon className="h-3.5 w-3.5" />
          {selectedCount > 0 ? (
            <span>
              {selectedCount} source{selectedCount !== 1 ? 's' : ''}
            </span>
          ) : (
            <span>All sources</span>
          )}
          <ChevronDownIcon className="h-3 w-3 text-muted-foreground" />
        </Button>
      </PopoverTrigger>

      <PopoverContent className="w-72 p-0" align="start" aria-label="Select knowledge sources">
        {/* Search */}
        <div className="flex items-center border-b border-border px-3 py-2">
          <SearchIcon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sources…"
            className="h-7 border-0 p-0 text-sm shadow-none focus-visible:ring-0"
            aria-label="Search sources"
          />
        </div>

        {/* List */}
        <ScrollArea className="max-h-64">
          {filtered.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              {sources.length === 0 ? 'No sources available.' : 'No matches.'}
            </div>
          ) : (
            <SourceListBox filtered={filtered} selectedIds={selectedIds} toggle={toggle} />
          )}
        </ScrollArea>

        {/* Footer */}
        {selectedCount > 0 && (
          <div className="border-t border-border px-3 py-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-full text-xs"
              onClick={() => onChange([])}
            >
              Clear selection
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
