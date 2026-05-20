'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { NeedsAttentionItem, NeedsAttentionKind } from '@/lib/api/analytics'
import { AlertTriangleIcon } from 'lucide-react'
import Link from 'next/link'
import { ChartCard } from './ChartCard'

const KIND_LABEL: Record<NeedsAttentionKind, string> = {
  connection: 'Connection',
  sync: 'Sync',
  study: 'Study',
}

function truncate(text: string | null | undefined, max = 90): string {
  if (!text) return 'See source for details'
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export interface NeedsAttentionPanelProps {
  data: NeedsAttentionItem[] | undefined
  loading: boolean
}

export function NeedsAttentionPanel({ data, loading }: NeedsAttentionPanelProps) {
  const items: NeedsAttentionItem[] = data ?? []

  return (
    <ChartCard
      title="Needs attention"
      actions={
        items.length > 0 ? (
          <span className="text-xs font-medium text-destructive tabular-nums">{items.length}</span>
        ) : null
      }
    >
      {loading ? (
        <div className="space-y-2">
          {['a', 'b', 'c'].map((k) => (
            <Skeleton key={k} className="h-9 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">All sources healthy ✓</p>
      ) : (
        <ul className="divide-y">
          {items.map((item) => (
            <li key={`${item.source_id}-${item.kind}`} className="py-2">
              <Link href={`/admin/sources/${item.source_id}`} className="group flex items-start gap-2 text-xs">
                <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-medium group-hover:underline" title={item.name}>
                      {item.name}
                    </span>
                    <Badge variant="outline" className="shrink-0 text-[10px]">
                      {KIND_LABEL[item.kind]}
                    </Badge>
                  </div>
                  <p className="truncate text-muted-foreground" title={item.detail ?? undefined}>
                    {truncate(item.detail)}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  )
}
