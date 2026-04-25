'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useTestEmbedderConnectionById } from '@/hooks/use-embedders'
import { cn } from '@/lib/utils'
import type { EmbedderPublic, TestConnectionStatus } from '@/types/embedder'
import { Loader2Icon, PencilIcon, PowerIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { toast } from 'sonner'

/**
 * Embedders listing — same structure as AI Models with extra columns:
 *   Dimensions, Active (yes/no), In-use (sources count).
 *
 * Activate action opens an `ActivateEmbedderDialog` (handled by the parent
 * page) which dry-runs the activation preview before kicking off the Celery
 * re-embed job.
 */

interface EmbeddersTableProps {
  items: readonly EmbedderPublic[]
  onEdit: (embedder: EmbedderPublic) => void
  onDelete: (embedder: EmbedderPublic) => void
  onActivate: (embedder: EmbedderPublic) => void
}

const STATUS_CLASS: Record<TestConnectionStatus, string> = {
  ok: 'bg-emerald-500',
  failed: 'bg-destructive',
  never: 'bg-muted-foreground/40',
}

const STATUS_LABEL: Record<TestConnectionStatus, string> = {
  ok: 'Healthy',
  failed: 'Failed',
  never: 'Untested',
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'Never'
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  const seconds = Math.round(diffMs / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString()
}

function maskKey(last4: string | null): string {
  if (!last4) return 'Not configured'
  return `••••• ····${last4}`
}

export function EmbeddersTable({ items, onEdit, onDelete, onActivate }: EmbeddersTableProps) {
  const testMutation = useTestEmbedderConnectionById()

  function handleTest(embedder: EmbedderPublic) {
    testMutation.mutate(embedder.id, {
      onSuccess: (result) => {
        if (result.ok) {
          toast.success(`${embedder.name}: OK (${result.latency_ms ?? '—'} ms)`)
        } else {
          toast.error(`${embedder.name}: ${result.error ?? 'Connection failed'}`)
        }
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : 'Connection failed'
        toast.error(`${embedder.name}: ${message}`)
      },
    })
  }

  if (items.length === 0) {
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Provider</TableHead>
            <TableHead>Model ID</TableHead>
            <TableHead>Dimensions</TableHead>
            <TableHead>Active</TableHead>
            <TableHead>In-use</TableHead>
            <TableHead>API key</TableHead>
            <TableHead>Last test</TableHead>
            <TableHead aria-label="Actions" />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell colSpan={9} className="py-12 text-center text-sm text-muted-foreground">
              No embedders configured.
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Provider</TableHead>
          <TableHead>Model ID</TableHead>
          <TableHead className="text-right">Dimensions</TableHead>
          <TableHead>Active</TableHead>
          <TableHead className="text-right">In-use</TableHead>
          <TableHead>API key</TableHead>
          <TableHead>Last test</TableHead>
          <TableHead aria-label="Actions" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((embedder) => {
          const isPending = testMutation.isPending && testMutation.variables === embedder.id
          return (
            <TableRow key={embedder.id}>
              <TableCell className="font-medium">{embedder.name}</TableCell>
              <TableCell>
                <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                  {embedder.provider}
                </Badge>
              </TableCell>
              <TableCell
                className="max-w-[200px] truncate font-mono text-xs"
                title={embedder.model_id}
              >
                {embedder.model_id}
              </TableCell>
              <TableCell className="text-right tabular-nums text-xs">
                {embedder.dimensions}
              </TableCell>
              <TableCell>
                {embedder.is_active ? (
                  <Badge className="bg-emerald-500/15 text-[10px] uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                    Active
                  </Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums text-xs">
                {embedder.in_use_sources}
              </TableCell>
              <TableCell className="font-mono text-xs">{maskKey(embedder.api_key_last4)}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={cn('h-2 w-2 rounded-full', STATUS_CLASS[embedder.last_test_status])}
                    aria-hidden
                  />
                  <span className="text-muted-foreground">
                    {STATUS_LABEL[embedder.last_test_status]} ·{' '}
                    {formatRelative(embedder.last_test_at)}
                  </span>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  {!embedder.is_active ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Activate ${embedder.name}`}
                      onClick={() => onActivate(embedder)}
                      title="Activate (requires re-index)"
                    >
                      <PowerIcon className="h-4 w-4" aria-hidden />
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Test ${embedder.name}`}
                    onClick={() => handleTest(embedder)}
                    disabled={isPending}
                  >
                    {isPending ? (
                      <Loader2Icon className="h-4 w-4 animate-spin" aria-hidden />
                    ) : (
                      <ZapIcon className="h-4 w-4" aria-hidden />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Edit ${embedder.name}`}
                    onClick={() => onEdit(embedder)}
                  >
                    <PencilIcon className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete ${embedder.name}`}
                    onClick={() => onDelete(embedder)}
                  >
                    <TrashIcon className="h-4 w-4 text-destructive" aria-hidden />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
