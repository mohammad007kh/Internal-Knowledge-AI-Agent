'use client'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  Database,
  FileSpreadsheet,
  FileText,
  FileType2,
  FolderOpen,
  Globe,
  Network,
  type LucideIcon,
} from 'lucide-react'

import type { SourceStatus, SourceType, SyncMode } from '@/lib/api/sources'

// ---------------------------------------------------------------------------
// Source type → icon + human label
// ---------------------------------------------------------------------------

interface SourceTypeMeta {
  icon: LucideIcon
  label: string
}

const SOURCE_TYPE_META: Record<string, SourceTypeMeta> = {
  // Databases
  postgresql: { icon: Database, label: 'PostgreSQL' },
  mysql: { icon: Database, label: 'MySQL' },
  mssql: { icon: Database, label: 'SQL Server' },
  mongodb: { icon: Database, label: 'MongoDB' },
  // Files
  pdf: { icon: FileText, label: 'PDF' },
  docx: { icon: FileText, label: 'Word' },
  xlsx: { icon: FileSpreadsheet, label: 'Excel' },
  csv: { icon: FileSpreadsheet, label: 'CSV' },
  txt: { icon: FileType2, label: 'Text' },
  markdown: { icon: FileType2, label: 'Markdown' },
  file_upload: { icon: FileText, label: 'File Upload' },
  // Web / SaaS
  web_url: { icon: Globe, label: 'Web URL' },
  confluence: { icon: Network, label: 'Confluence' },
  sharepoint: { icon: FolderOpen, label: 'SharePoint' },
  google_drive: { icon: FolderOpen, label: 'Google Drive' },
  notion: { icon: FileText, label: 'Notion' },
}

export function getSourceTypeMeta(type: SourceType | string): SourceTypeMeta {
  return SOURCE_TYPE_META[type] ?? { icon: Database, label: type }
}

export function SourceTypeCell({ type }: { type: SourceType | string }) {
  const { icon: Icon, label } = getSourceTypeMeta(type)
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
      <span className="text-sm">{label}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status badge with colour mapping
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-300 border-zinc-500/30',
  syncing: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30',
  running: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30',
  ready: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  completed: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  success: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  error: 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30',
  failed: 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30',
  disabled: 'bg-zinc-500/15 text-zinc-500 dark:text-zinc-400 border-zinc-500/30',
}

export function StatusBadge({ status }: { status: SourceStatus | string | undefined | null }) {
  const value = status ?? 'pending'
  const cls = STATUS_STYLES[value] ?? STATUS_STYLES.disabled
  return (
    <Badge variant="outline" className={cn('capitalize font-medium', cls)}>
      {value}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Source mode badge (snapshot / live)
// ---------------------------------------------------------------------------

export function SourceModeBadge({ mode }: { mode: string | undefined | null }) {
  if (!mode) return <span className="text-muted-foreground text-xs">—</span>
  const isLive = mode === 'live'
  return (
    <Badge
      variant="outline"
      className={cn(
        'capitalize font-medium',
        isLive
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30'
          : 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border-indigo-500/30'
      )}
    >
      {mode}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Sync mode badge
// ---------------------------------------------------------------------------

export function SyncModeBadge({ mode }: { mode: SyncMode | string | undefined | null }) {
  if (!mode) return <span className="text-muted-foreground text-xs">—</span>
  return (
    <Badge variant="secondary" className="capitalize">
      {mode}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Retrieval mode badge
// ---------------------------------------------------------------------------

export function RetrievalModeBadge({ mode }: { mode: string | undefined | null }) {
  if (!mode) return <span className="text-muted-foreground text-xs">—</span>
  const pretty = mode.replace(/_/g, ' ')
  return (
    <Badge variant="secondary" className="capitalize">
      {pretty}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Formatted timestamp with relative hint
// ---------------------------------------------------------------------------

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
