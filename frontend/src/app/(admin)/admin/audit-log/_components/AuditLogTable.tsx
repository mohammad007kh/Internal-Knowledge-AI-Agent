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
import type { AuditLogEntry } from '@/lib/api/audit-log'
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, CopyIcon } from 'lucide-react'
import { useCallback, useState } from 'react'

interface AuditLogTableProps {
  items: readonly AuditLogEntry[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
}

function formatTimestamp(value: string): string {
  // ISO → 'Mon DD, YYYY HH:mm:ss' (locale-aware) — keeps the column compact.
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function truncateUuid(value: string): string {
  if (value.length <= 12) return value
  return `${value.slice(0, 8)}…${value.slice(-4)}`
}

interface CopyableUuidProps {
  value: string
  label: string
}

function CopyableUuid({ value, label }: CopyableUuidProps) {
  const [copied, setCopied] = useState(false)

  const onCopy = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return
    navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(true)
        const handle = setTimeout(() => setCopied(false), 1200)
        return () => clearTimeout(handle)
      })
      .catch(() => {
        // Clipboard write can fail in iframes / insecure contexts — silently
        // ignore.  The text is still selectable so the admin can copy by hand.
      })
  }, [value])

  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs">
      <span title={value}>{truncateUuid(value)}</span>
      <button
        type="button"
        onClick={onCopy}
        aria-label={`Copy ${label}`}
        data-testid="copy-id-button"
        className="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      >
        {copied ? (
          <CheckIcon className="h-3 w-3 text-emerald-600" aria-hidden />
        ) : (
          <CopyIcon className="h-3 w-3" aria-hidden />
        )}
      </button>
    </span>
  )
}

interface MetadataCellProps {
  rowId: string
  metadata: Record<string, unknown>
  expanded: boolean
  onToggle: (rowId: string) => void
}

function MetadataCell({ rowId, metadata, expanded, onToggle }: MetadataCellProps) {
  const isEmpty = Object.keys(metadata).length === 0
  if (isEmpty) {
    return <span className="text-xs italic text-muted-foreground">—</span>
  }

  const oneLine = JSON.stringify(metadata)
  // 70-char preview — long enough to glance but short enough to stay on one
  // line at most viewport widths.
  const preview = oneLine.length > 70 ? `${oneLine.slice(0, 70)}…` : oneLine

  return (
    <button
      type="button"
      onClick={() => onToggle(rowId)}
      data-testid="metadata-toggle"
      aria-expanded={expanded}
      className="block max-w-[420px] cursor-pointer text-left text-xs hover:underline"
    >
      {expanded ? (
        <pre className="whitespace-pre-wrap break-all rounded bg-muted/50 p-2 font-mono">
          {JSON.stringify(metadata, null, 2)}
        </pre>
      ) : (
        <code
          className="font-mono text-muted-foreground"
          title="Click to expand"
        >
          {preview}
        </code>
      )}
    </button>
  )
}

export function AuditLogTable({
  items,
  total,
  page,
  pageSize,
  onPageChange,
}: AuditLogTableProps) {
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const toggleRow = useCallback((rowId: string) => {
    setExpandedRow((prev) => (prev === rowId ? null : rowId))
  }, [])

  const lastPage = Math.max(1, Math.ceil(total / pageSize))
  const isFirstPage = page <= 1
  const isLastPage = page >= lastPage
  const showFooter = total > pageSize

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-md border">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/75">
            <TableRow>
              <TableHead className="w-[180px]">Timestamp</TableHead>
              <TableHead className="w-[200px]">Actor</TableHead>
              <TableHead className="w-[180px]">Action</TableHead>
              <TableHead className="w-[140px]">Resource</TableHead>
              <TableHead className="w-[180px]">Resource ID</TableHead>
              <TableHead>Metadata</TableHead>
              <TableHead className="w-[140px]">IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row) => {
              const isExpanded = expandedRow === row.id
              return (
                <TableRow
                  key={row.id}
                  data-testid="audit-log-row"
                  className="hover:bg-muted/30"
                >
                  <TableCell className="text-xs text-muted-foreground tabular-nums">
                    {formatTimestamp(row.created_at)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {row.admin_user_email ? (
                      <span className="truncate" title={row.admin_user_email}>
                        {row.admin_user_email}
                      </span>
                    ) : (
                      <span className="text-xs italic text-muted-foreground">system</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {row.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {row.resource_type}
                  </TableCell>
                  <TableCell>
                    {row.resource_id ? (
                      <CopyableUuid value={row.resource_id} label="resource ID" />
                    ) : (
                      <span className="text-xs italic text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <MetadataCell
                      rowId={row.id}
                      metadata={row.metadata}
                      expanded={isExpanded}
                      onToggle={toggleRow}
                    />
                  </TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {row.ip_address ?? '—'}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {showFooter ? (
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="tabular-nums">
            Page {page} of {lastPage} · {total.toLocaleString()} entries
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page - 1)}
              disabled={isFirstPage}
              aria-label="Previous page"
              data-testid="audit-log-prev"
            >
              <ChevronLeftIcon className="mr-1 h-3.5 w-3.5" aria-hidden />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page + 1)}
              disabled={isLastPage}
              aria-label="Next page"
              data-testid="audit-log-next"
            >
              Next
              <ChevronRightIcon className="ml-1 h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
