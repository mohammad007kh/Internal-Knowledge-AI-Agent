'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  useGuardrailEvent,
  useGuardrailEvents,
  usePolicy,
  useUpdatePolicy,
} from '@/features/policy/hooks/usePolicy'
import type { GuardrailAction, GuardrailType } from '@/lib/api/policy'
import { getErrorMessage } from '@/lib/errors'
import { ShieldAlertIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

type GuardrailTypeFilter = GuardrailType | 'all'
type GuardrailActionFilter = GuardrailAction | 'all'

const PAGE_SIZE = 20

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function PolicyEditor() {
  const { data, isLoading, isError, error, refetch } = usePolicy()
  const updatePolicy = useUpdatePolicy()
  const [draft, setDraft] = useState('')

  useEffect(() => {
    if (data) setDraft(data.content ?? '')
  }, [data])

  const isDirty = data ? draft !== (data.content ?? '') : false

  useEffect(() => {
    if (!isDirty) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  if (isLoading) return <Skeleton className="h-64 w-full" />
  if (isError)
    return <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />

  return (
    <Card>
      <CardHeader>
        <CardTitle>Company policy</CardTitle>
        <CardDescription>
          Natural-language policy applied to all incoming queries. Saved changes take effect immediately.
          {data?.created_at && (
            <span className="ml-1 text-xs">Last updated {formatDate(data.created_at)}.</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={10}
          className="font-mono text-sm"
          placeholder="Describe what users can and cannot ask about…"
        />
        <div className="flex flex-col gap-2 sm:flex-row">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button className="w-full sm:w-auto" disabled={!isDirty || updatePolicy.isPending}>
                {updatePolicy.isPending ? 'Saving…' : 'Review & save'}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="max-w-2xl">
              <AlertDialogHeader>
                <AlertDialogTitle>Publish policy change?</AlertDialogTitle>
                <AlertDialogDescription>
                  This policy update takes effect immediately for all users. Review the
                  changes below before publishing.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-words">
                {draft}
              </pre>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep editing</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => updatePolicy.mutate({ content: draft })}
                >
                  Publish changes
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          {isDirty && (
            <Button
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => setDraft(data?.content ?? '')}
              disabled={updatePolicy.isPending}
            >
              Discard changes
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function GuardrailEventsTab() {
  const [typeFilter, setTypeFilter] = useState<GuardrailTypeFilter>('all')
  const [actionFilter, setActionFilter] = useState<GuardrailActionFilter>('all')
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filters = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      ...(typeFilter !== 'all' ? { guard_type: typeFilter } : {}),
      ...(actionFilter !== 'all' ? { action: actionFilter } : {}),
    }),
    [typeFilter, actionFilter, offset]
  )

  const { data, isLoading, isError, error, refetch } = useGuardrailEvents(filters)
  const detail = useGuardrailEvent(selectedId)

  function handleTypeChange(v: string) {
    setTypeFilter(v as GuardrailTypeFilter)
    setOffset(0)
  }
  function handleActionChange(v: string) {
    setActionFilter(v as GuardrailActionFilter)
    setOffset(0)
  }

  const total = data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Type</span>
          <Select value={typeFilter} onValueChange={handleTypeChange}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="input">Input</SelectItem>
              <SelectItem value="output">Output</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Action</span>
          <Select value={actionFilter} onValueChange={handleActionChange}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="blocked">Blocked</SelectItem>
              <SelectItem value="logged">Logged</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      )}

      {data && data.items.length === 0 && (
        <EmptyState
          icon={ShieldAlertIcon}
          title="No guardrail events"
          description="No messages have been flagged yet."
        />
      )}

      {data && data.items.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-md border">
            <Table className="min-w-[720px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Input</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((event) => (
                  <TableRow
                    key={event.id}
                    tabIndex={0}
                    role="button"
                    aria-label={`View guardrail event from ${formatDate(event.created_at)}`}
                    onClick={() => setSelectedId(event.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedId(event.id)
                      }
                    }}
                    className="cursor-pointer focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatDate(event.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{event.guard_type}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={event.action === 'blocked' ? 'destructive' : 'secondary'}
                      >
                        {event.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[420px] truncate text-sm">
                      {event.original_input?.slice(0, 100) ?? ''}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={!hasPrev}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={!hasNext}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      <Dialog open={!!selectedId} onOpenChange={(open) => !open && setSelectedId(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Guardrail event</DialogTitle>
            <DialogDescription>
              Full payload for the selected event.
            </DialogDescription>
          </DialogHeader>
          {detail.isLoading && <Skeleton className="h-40 w-full" />}
          {detail.isError && (
            <ErrorState
              message={getErrorMessage(detail.error)}
              onRetry={() => detail.refetch()}
            />
          )}
          {detail.data && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-3 gap-2">
                <span className="text-muted-foreground">Type</span>
                <span className="col-span-2">
                  <Badge variant="secondary">{detail.data.guard_type}</Badge>
                </span>
                <span className="text-muted-foreground">Action</span>
                <span className="col-span-2">
                  <Badge
                    variant={detail.data.action === 'blocked' ? 'destructive' : 'secondary'}
                  >
                    {detail.data.action}
                  </Badge>
                </span>
                <span className="text-muted-foreground">Time</span>
                <span className="col-span-2">{formatDate(detail.data.created_at)}</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-1">Input</p>
                <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-words max-h-96 overflow-auto">
                  {detail.data.original_input ?? '—'}
                </pre>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default function PolicyPage() {
  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h1 className="text-xl font-semibold">Policy &amp; guardrails</h1>
        <p className="text-sm text-muted-foreground">
          Manage the company policy and audit guardrail events.
        </p>
      </div>
      <Tabs defaultValue="policy">
        <TabsList>
          <TabsTrigger value="policy">Policy</TabsTrigger>
          <TabsTrigger value="events">Guardrail events</TabsTrigger>
        </TabsList>
        <TabsContent value="policy" className="pt-4">
          <PolicyEditor />
        </TabsContent>
        <TabsContent value="events" className="pt-4">
          <GuardrailEventsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
