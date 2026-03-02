'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { XIcon } from 'lucide-react'
import type { SourceSummary } from './SourceSelector'

interface SourceChipsProps {
  sources: SourceSummary[]
  onRemove: (id: string) => void
  disabled?: boolean
}

export function SourceChips({ sources, onRemove, disabled }: SourceChipsProps) {
  if (sources.length === 0) return null

  return (
    <ul
      className="flex flex-wrap gap-1.5 border-t border-border bg-background px-4 py-2"
      aria-label="Selected sources"
    >
      {sources.map((s) => (
        <li key={s.id}>
          <Badge variant="secondary" className="flex items-center gap-1 pr-1">
            <span className="max-w-[120px] truncate text-xs">{s.name}</span>
            <Button
              size="icon"
              variant="ghost"
              className="h-4 w-4 shrink-0 hover:bg-transparent"
              onClick={() => onRemove(s.id)}
              disabled={disabled}
              aria-label={`Remove source: ${s.name}`}
            >
              <XIcon className="h-3 w-3" />
            </Button>
          </Badge>
        </li>
      ))}
    </ul>
  )
}
