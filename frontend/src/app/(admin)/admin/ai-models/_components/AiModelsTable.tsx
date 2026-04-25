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
import { useTestAiModelConnectionById } from '@/hooks/use-ai-models'
import { cn } from '@/lib/utils'
import type { AIModelPublic, TestConnectionStatus } from '@/types/ai-model'
import { Loader2Icon, PencilIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { toast } from 'sonner'

/**
 * AI Models listing — columns per design doc §8.1:
 *   Name, Provider, Model ID, Base URL, API key (masked), Last test,
 *   Used by (count), Updated.
 *
 * Row actions: Edit (opens Sheet), Test connection (record-bound endpoint),
 * Delete (opens AlertDialog with usage check).
 */

interface AiModelsTableProps {
  items: readonly AIModelPublic[]
  onEdit: (model: AIModelPublic) => void
  onDelete: (model: AIModelPublic) => void
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

export function AiModelsTable({ items, onEdit, onDelete }: AiModelsTableProps) {
  const testMutation = useTestAiModelConnectionById()

  function handleTest(model: AIModelPublic) {
    testMutation.mutate(model.id, {
      onSuccess: (result) => {
        if (result.ok) {
          toast.success(`${model.name}: OK (${result.latency_ms ?? '—'} ms)`)
        } else {
          toast.error(`${model.name}: ${result.error ?? 'Connection failed'}`)
        }
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : 'Connection failed'
        toast.error(`${model.name}: ${message}`)
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
            <TableHead>Base URL</TableHead>
            <TableHead>API key</TableHead>
            <TableHead>Last test</TableHead>
            <TableHead>Updated</TableHead>
            <TableHead aria-label="Actions" />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell colSpan={8} className="py-12 text-center text-sm text-muted-foreground">
              No AI models configured.
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
          <TableHead>Base URL</TableHead>
          <TableHead>API key</TableHead>
          <TableHead>Last test</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead aria-label="Actions" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((model) => {
          const isPending = testMutation.isPending && testMutation.variables === model.id
          return (
            <TableRow key={model.id}>
              <TableCell className="font-medium">
                <div className="flex flex-col">
                  <span>{model.name}</span>
                  {!model.is_active ? (
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Disabled
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                  {model.provider}
                </Badge>
              </TableCell>
              <TableCell
                className="max-w-[200px] truncate font-mono text-xs"
                title={model.model_id}
              >
                {model.model_id}
              </TableCell>
              <TableCell
                className="max-w-[200px] truncate text-xs text-muted-foreground"
                title={model.base_url ?? 'Provider default'}
              >
                {model.base_url ?? <span className="italic">default</span>}
              </TableCell>
              <TableCell className="font-mono text-xs">{maskKey(model.api_key_last4)}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={cn('h-2 w-2 rounded-full', STATUS_CLASS[model.last_test_status])}
                    aria-hidden
                  />
                  <span className="text-muted-foreground">
                    {STATUS_LABEL[model.last_test_status]} · {formatRelative(model.last_test_at)}
                  </span>
                </div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatRelative(model.updated_at)}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Test ${model.name}`}
                    onClick={() => handleTest(model)}
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
                    aria-label={`Edit ${model.name}`}
                    onClick={() => onEdit(model)}
                  >
                    <PencilIcon className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete ${model.name}`}
                    onClick={() => onDelete(model)}
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
