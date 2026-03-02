'use client'

import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { apiClient } from '@/lib/api-client'

interface SourceDetail {
  id: string
  name: string
  connector_type: string
  status: string
  document_count: number
  last_synced_at: string | null
  created_at: string
}

interface Document {
  id: string
  title: string
  url: string | null
  created_at: string
}

interface SyncRun {
  id: string
  started_at: string
  completed_at: string | null
  status: string
  documents_indexed: number | null
  error_message: string | null
}

interface DocumentsResponse {
  items: Document[]
  total: number
}

interface SyncHistoryResponse {
  items: SyncRun[]
  total: number
}

async function fetchSource(id: string): Promise<SourceDetail> {
  const res = await apiClient.get<SourceDetail>(`/sources/${id}`)
  return res.data
}

async function fetchDocuments(id: string): Promise<DocumentsResponse> {
  const res = await apiClient.get<DocumentsResponse>(`/sources/${id}/documents?page=1&page_size=20`)
  return res.data
}

async function fetchSyncHistory(id: string): Promise<SyncHistoryResponse> {
  const res = await apiClient.get<SyncHistoryResponse>(
    `/sources/${id}/sync-runs?page=1&page_size=20`
  )
  return res.data
}

function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, string> = {
    ready: 'bg-green-600/15 text-green-700 dark:text-green-400',
    syncing: 'bg-blue-600/15 text-blue-700 dark:text-blue-400',
    error: 'bg-red-600/15 text-red-700 dark:text-red-400',
    pending: 'bg-yellow-600/15 text-yellow-700 dark:text-yellow-400',
    disabled: 'bg-zinc-600/15 text-zinc-500 dark:text-zinc-400',
  }
  const cls = variantMap[status] ?? variantMap.disabled
  return (
    <Badge className={cls} variant="outline">
      {status}
    </Badge>
  )
}

function DocumentsTab({ sourceId }: { sourceId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['source-documents', sourceId],
    queryFn: () => fetchDocuments(sourceId),
  })

  if (isLoading) {
    return <p className="text-muted-foreground py-4 text-sm">Loading documents…</p>
  }

  if (!data?.items.length) {
    return <p className="text-muted-foreground py-4 text-sm">No documents indexed yet.</p>
  }

  return (
    <div className="space-y-1">
      <p className="text-muted-foreground mb-3 text-xs">
        {data.total} document{data.total !== 1 ? 's' : ''} indexed
      </p>
      <div className="divide-y rounded-md border">
        {data.items.map((doc) => (
          <div className="flex items-center justify-between px-4 py-3" key={doc.id}>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{doc.title}</p>
              {doc.url && (
                <a
                  className="text-muted-foreground truncate text-xs hover:underline"
                  href={doc.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {doc.url}
                </a>
              )}
            </div>
            <span className="text-muted-foreground ml-4 shrink-0 text-xs">
              {new Date(doc.created_at).toLocaleDateString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function SyncHistoryTab({ sourceId }: { sourceId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['source-sync-history', sourceId],
    queryFn: () => fetchSyncHistory(sourceId),
  })

  if (isLoading) {
    return <p className="text-muted-foreground py-4 text-sm">Loading sync history…</p>
  }

  if (!data?.items.length) {
    return <p className="text-muted-foreground py-4 text-sm">No sync runs yet.</p>
  }

  return (
    <div className="divide-y rounded-md border">
      {data.items.map((run) => (
        <div className="px-4 py-3" key={run.id}>
          <div className="flex items-center justify-between">
            <StatusBadge status={run.status} />
            <span className="text-muted-foreground text-xs">
              {new Date(run.started_at).toLocaleString()}
            </span>
          </div>
          {run.documents_indexed !== null && (
            <p className="mt-1 text-sm">
              {run.documents_indexed} document{run.documents_indexed !== 1 ? 's' : ''} indexed
            </p>
          )}
          {run.error_message && (
            <p className="mt-1 text-sm text-red-600 dark:text-red-400">{run.error_message}</p>
          )}
        </div>
      ))}
    </div>
  )
}

export default function SourceDetailPage() {
  const { id } = useParams<{ id: string }>()

  const { data: source, isLoading } = useQuery({
    queryKey: ['source', id],
    queryFn: () => fetchSource(id),
    enabled: Boolean(id),
  })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <span className="text-muted-foreground text-sm">Loading…</span>
      </div>
    )
  }

  if (!source) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground text-sm">Source not found.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{source.name}</h1>
          <p className="text-muted-foreground mt-1 text-sm font-mono">{source.connector_type}</p>
        </div>
        <StatusBadge status={source.status} />
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="rounded-md border p-3">
          <p className="text-muted-foreground text-xs">Documents</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{source.document_count}</p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-muted-foreground text-xs">Last Synced</p>
          <p className="mt-1 text-sm">
            {source.last_synced_at ? new Date(source.last_synced_at).toLocaleString() : 'Never'}
          </p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-muted-foreground text-xs">Created</p>
          <p className="mt-1 text-sm">{new Date(source.created_at).toLocaleDateString()}</p>
        </div>
      </div>

      <Tabs defaultValue="documents">
        <TabsList>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="sync-history">Sync History</TabsTrigger>
        </TabsList>
        <TabsContent className="mt-4" value="documents">
          <DocumentsTab sourceId={id} />
        </TabsContent>
        <TabsContent className="mt-4" value="sync-history">
          <SyncHistoryTab sourceId={id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
