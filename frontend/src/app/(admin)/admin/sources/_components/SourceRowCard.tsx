'use client'

import { ActionCell } from '@/app/(admin)/admin/sources/_components/ActionCell'
import { IngestionStrip } from '@/app/(admin)/admin/sources/_components/IngestionStrip'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { formatRelative } from '@/features/sources/format'
import { SourceModeBadge, getSourceTypeMeta } from '@/features/sources/source-ui'
import type { SourceListItem } from '@/lib/api/sources'
import { Eye, MoreHorizontal, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

interface SourceRowCardProps {
  source: SourceListItem
  /** Retained for prop compatibility; mobile action now lives in `ActionCell`. */
  isSyncing?: boolean
  /** Retained for prop compatibility; mobile action now lives in `ActionCell`. */
  onSync?: (id: string) => void
  onDelete: (id: string) => void
}

/**
 * Compact card representation of a source row, used on small viewports where
 * the table would otherwise force horizontal scroll.
 */
export function SourceRowCard({ source, onDelete }: SourceRowCardProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const meta = getSourceTypeMeta(source.source_type)
  const Icon = meta.icon

  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"
          aria-hidden
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <Link
            href={`/admin/sources/${source.id}`}
            className="block truncate font-medium text-foreground hover:underline"
          >
            {source.name}
          </Link>
          <p className="truncate text-xs text-muted-foreground">
            {source.description ?? meta.label}
          </p>
        </div>
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label={`More actions for ${source.name}`}
              className="-mt-1 h-8 w-8 p-0"
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-44 p-1">
            <Link
              href={`/admin/sources/${source.id}`}
              onClick={() => setMenuOpen(false)}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
            >
              <Eye className="h-4 w-4" aria-hidden />
              View details
            </Link>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false)
                onDelete(source.id)
              }}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Delete
            </button>
          </PopoverContent>
        </Popover>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <SourceModeBadge mode={source.source_mode} />
      </div>

      <div className="mt-3">
        <IngestionStrip source={source} />
      </div>

      <div className="mt-3 text-xs">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Last synced</p>
        <p className="mt-0.5 text-foreground">{formatRelative(source.last_synced_at)}</p>
      </div>

      <div className="mt-3">
        <ActionCell source={source} layout="block" />
      </div>
    </div>
  )
}
