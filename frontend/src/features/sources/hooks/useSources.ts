'use client'

import {
  type SchemaDocumentResponse,
  type SourceConnectionConfig,
  type SourceDetail,
  type SourceIntent,
  type SourceIntentUpdate,
  type SourceListItem,
  type UpdateSourceRequest,
  autoNameApi,
  cancelSyncJobApi,
  deleteSourceApi,
  getIntentApi,
  getSchemaDocumentApi,
  getSourceApi,
  getSourceConnectionConfigApi,
  getSourceStatsApi,
  listSourceDocumentsApi,
  listSourcesApi,
  listSyncJobsApi,
  proposeIntentApi,
  putIntentApi,
  refreshDescriptionApi,
  testConnectionApi,
  triggerSyncApi,
  updateSourceApi,
} from '@/lib/api/sources'
import { extractApiErrorMessage } from '@/lib/api-error'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

// ---------------------------------------------------------------------------
// Query key factory — single source of truth
// ---------------------------------------------------------------------------

export const sourcesKeys = {
  all: ['sources'] as const,
  list: () => [...sourcesKeys.all, 'list'] as const,
  detail: (id: string) => [...sourcesKeys.all, 'detail', id] as const,
  stats: (id: string) => [...sourcesKeys.all, 'stats', id] as const,
  // Sync jobs are paginated — the key includes limit/offset so each page is
  // cached independently and Previous/Next don't blow away other pages.
  syncJobs: (id: string, limit?: number, offset?: number) =>
    limit === undefined && offset === undefined
      ? ([...sourcesKeys.all, 'sync-jobs', id] as const)
      : ([...sourcesKeys.all, 'sync-jobs', id, { limit, offset }] as const),
  documents: (id: string) => [...sourcesKeys.all, 'documents', id] as const,
  schemaDocument: (id: string) =>
    [...sourcesKeys.all, 'schema-document', id] as const,
  connectionConfig: (id: string) =>
    [...sourcesKeys.all, 'connection-config', id] as const,
  intent: (id: string) => [...sourcesKeys.all, 'intent', id] as const,
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export interface UseListSourcesOptions {
  /**
   * When `true`, refetch every 5 seconds. Callers should set this when any
   * visible row is in the `running` phase so the verb column transitions out
   * of "Working on it…" promptly. When `false` (default), the query stays on
   * the React Query default (no polling, refetch on focus). `'auto'` reads
   * the cached list and polls while ANY row is still moving through its
   * lifecycle — sync running/pending, AI naming pending, or schema study in
   * flight. Falls back to no polling when every row is steady-state.
   */
  pollWhileRunning?: boolean | 'auto'
}

export function useListSources(options: UseListSourcesOptions = {}) {
  const { pollWhileRunning = false } = options
  return useQuery({
    queryKey: sourcesKeys.list(),
    queryFn: () => listSourcesApi(),
    refetchInterval:
      pollWhileRunning === 'auto'
        ? (query) => {
            const items = query.state.data?.items ?? []
            return items.some(shouldPollSourceLifecycle) ? 5_000 : false
          }
        : pollWhileRunning
          ? 5_000
          : false,
  })
}

export interface UseSourceOptions {
  /**
   * When `true`, refetch the source detail every 3 seconds. Callers can pass
   * the static `true`/`false`, but the more useful pattern is to derive this
   * from the query's own data — e.g. "poll while `latest_job.status` is in
   * flight". To support that without a chicken-and-egg, the hook also accepts
   * `'auto'`: it inspects the cached source and polls while ANY part of the
   * lifecycle is still moving — sync job pending/running, AI naming pending,
   * or schema-study in flight. Defaults to `false` (no polling).
   */
  pollWhileRunning?: boolean | 'auto'
}

/**
 * Should we be polling? Inspect every lifecycle signal — not just the sync
 * job — so the page stays warm while AI naming or the DB study are still
 * working. Exported for the (separate) useListSources hook that needs the
 * same predicate run across many rows.
 */
export function shouldPollSourceLifecycle(
  source: SourceListItem | SourceDetail | null | undefined
): boolean {
  if (!source) return false
  const jobStatus = source.latest_job?.status
  if (jobStatus === 'pending' || jobStatus === 'running') return true
  if (source.name_status === 'pending_ai') return true
  if (source.description_status === 'pending_ai') return true
  // FX41 — schema_status is lowercase on the wire; 'queued' lives on
  // study_state (uppercase), not on schema_status.
  if (source.schema_status === 'studying' || source.study_state === 'QUEUED') {
    return true
  }
  return false
}

export function useSource(
  sourceId: string | undefined,
  options: UseSourceOptions = {}
) {
  const { pollWhileRunning = false } = options
  return useQuery({
    queryKey: sourceId ? sourcesKeys.detail(sourceId) : ['sources', 'detail', 'empty'],
    queryFn: () => getSourceApi(sourceId as string),
    enabled: Boolean(sourceId),
    refetchInterval:
      pollWhileRunning === 'auto'
        ? (query) => (shouldPollSourceLifecycle(query.state.data) ? 3_000 : false)
        : pollWhileRunning
          ? 3_000
          : false,
  })
}

/**
 * Watch the cached source's lifecycle phase and invalidate sibling queries
 * whenever it changes. Used by the source-detail page so that when ingestion
 * flips from running → ready, the sources LIST query (used by the chat
 * session source picker, which keys on `[...sourcesKeys.list(),
 * { availableOnly: true }]` — same prefix) and the chat session messages
 * query refetch immediately.
 *
 * The hook stores the previous phase in a ref so the invalidation only fires
 * on the actual transition, not on every render.
 */
export function usePhaseTransitionInvalidation(
  sourceId: string | undefined,
  currentPhase: string | null | undefined
): void {
  const queryClient = useQueryClient()
  // Separate refs for "have we mounted yet" and "previous phase value" so the
  // mount-skip is explicit and survives React 18 StrictMode's double-invoke
  // (refs are NOT reset between Strict mount/unmount/mount). Without this
  // split, the guard had to combine `prev !== undefined && prev !== null` to
  // catch both first-render and loading-state transitions — fragile and easy
  // to misread.
  const hasMountedRef = useRef(false)
  const prevPhaseRef = useRef<string | null | undefined>(currentPhase)
  useEffect(() => {
    if (!sourceId) return
    const prev = prevPhaseRef.current
    prevPhaseRef.current = currentPhase
    if (!hasMountedRef.current) {
      // First effect run for this hook instance. Page already has fresh data
      // for the current phase; transitions only matter while on-screen.
      hasMountedRef.current = true
      return
    }
    if (prev === currentPhase) return
    // exact: false makes the prefix-match intent explicit: the chat session
    // source picker key is `[...sourcesKeys.list(), { availableOnly: true }]`
    // — a child of `sourcesKeys.list()`. React Query v5 prefix-matches arrays
    // by default, but spelling it out makes the contract robust to future
    // sourcesKeys evolution.
    queryClient.invalidateQueries({ queryKey: sourcesKeys.list(), exact: false })
    queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId), exact: false })
    queryClient.invalidateQueries({ queryKey: sourcesKeys.stats(sourceId), exact: false })
  }, [sourceId, currentPhase, queryClient])
}

export function useSourceStats(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.stats(sourceId) : ['sources', 'stats', 'empty'],
    queryFn: () => getSourceStatsApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

export interface UseSyncJobsOptions {
  limit?: number
  offset?: number
  /**
   * When `true`, refetch the sync-jobs page every 3 seconds. Callers should
   * set this while a sync is in flight so the freshly-completed row appears
   * in the history without manual refresh. Defaults to `false`.
   */
  pollWhileRunning?: boolean
}

/**
 * Paginated sync-jobs query. `limit` defaults to the API's default (20) and
 * `offset` to 0. Each (sourceId, limit, offset) tuple is cached independently
 * — Previous/Next on the detail page reuse cached pages instantly.
 *
 * Backwards compatible with the previous `useSyncJobs(id)` call site: omit the
 * options object and the hook keeps the original behavior.
 */
export function useSyncJobs(sourceId: string | undefined, options: UseSyncJobsOptions = {}) {
  const { limit, offset, pollWhileRunning = false } = options
  return useQuery({
    queryKey: sourceId
      ? sourcesKeys.syncJobs(sourceId, limit, offset)
      : ['sources', 'sync-jobs', 'empty'],
    queryFn: () => listSyncJobsApi(sourceId as string, limit, offset),
    enabled: Boolean(sourceId),
    refetchInterval: pollWhileRunning ? 3_000 : false,
  })
}

/**
 * Paginated sync-jobs query that auto-polls while a job is in flight. Takes
 * the latest job status off the source detail (passed in by the caller — we
 * don't fetch it again). This keeps polling in sync with the detail query
 * without each tab maintaining its own timer.
 */

export function useSourceDocuments(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.documents(sourceId) : ['sources', 'documents', 'empty'],
    queryFn: () => listSourceDocumentsApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

export interface UseSchemaDocumentOptions {
  /**
   * Gate the query — pass `sourceType === 'database'` so the hook stays
   * dormant for file / web / Confluence sources where the endpoint would
   * always 404. Defaults to `true` (always enabled when a sourceId is
   * present) so calling code that already knows the source is a DB doesn't
   * have to pass a redundant flag.
   */
  enabled?: boolean
}

/**
 * Fetch the latest validated SchemaDocument for a DB source.
 *
 * No auto-polling — the document only changes when the studying agent
 * completes a new run, and we invalidate the cache from `useTriggerSync`
 * (which already invalidates `sourcesKeys.detail`). `staleTime: 60_000`
 * because the document is large and changes rarely; we don't want to
 * refetch on every tab switch.
 */
export function useSchemaDocument(
  sourceId: string | undefined,
  options: UseSchemaDocumentOptions = {}
) {
  const { enabled = true } = options
  return useQuery<SchemaDocumentResponse>({
    queryKey: sourceId
      ? sourcesKeys.schemaDocument(sourceId)
      : ['sources', 'schema-document', 'empty'],
    queryFn: () => getSchemaDocumentApi(sourceId as string),
    enabled: Boolean(sourceId) && enabled,
    staleTime: 60_000,
    // 404 is an expected state ("no study has run yet") — don't retry.
    retry: false,
  })
}

export interface UseSourceConnectionConfigOptions {
  /**
   * Gate the fetch. The EditCredentialsDialog passes `open` here so the
   * config is only fetched when the dialog is actually shown.
   */
  enabled?: boolean
}

/**
 * Fetch the non-secret connection metadata for a DB source (FX7).
 *
 * Drives the EditCredentialsDialog pre-fill. The response never contains the
 * password or the raw connection string — only db_type/host/port/database/
 * username/ssl_mode/collection/query and a `has_password` flag. `staleTime`
 * is short (the config changes only on a credential rotation, which already
 * invalidates `sourcesKeys.detail`); we still refetch each time the dialog
 * opens so a rotation made elsewhere is reflected.
 */
export function useSourceConnectionConfig(
  sourceId: string | undefined,
  options: UseSourceConnectionConfigOptions = {}
) {
  const { enabled = true } = options
  return useQuery<SourceConnectionConfig>({
    queryKey: sourceId
      ? sourcesKeys.connectionConfig(sourceId)
      : ['sources', 'connection-config', 'empty'],
    queryFn: () => getSourceConnectionConfigApi(sourceId as string),
    enabled: Boolean(sourceId) && enabled,
    // Don't keep a stale snapshot across dialog opens — refetch on mount.
    staleTime: 0,
    // 4xx (e.g. a non-DB source) is a "won't change on retry" state.
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useUpdateSource(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateSourceRequest) => updateSourceApi(sourceId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
    },
  })
}

export function useDeleteSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => deleteSourceApi(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success('Source deleted.')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to delete source')
    },
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (sourceId: string) => testConnectionApi(sourceId),
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message || 'Connection successful')
      } else {
        toast.error(data.message || 'Connection failed')
      }
    },
    onError: (error: unknown) => {
      // Surface the backend's actual reason (e.g. "Could not connect to
      // database source") rather than the generic axios string.
      toast.error(extractApiErrorMessage(error))
    },
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => triggerSyncApi(sourceId),
    onSuccess: (_data, sourceId) => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.syncJobs(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.stats(sourceId) })
    },
  })
}

/**
 * U16 — Stop an in-flight sync. Mutation keyed on `{ sourceId, jobId }`.
 * On success, invalidates the detail + sync-jobs caches so the
 * source-detail page re-fetches and reflects the new `cancelled` status
 * (or the cooperatively-pending `running` row that will flip on its next
 * checkpoint).
 */
export interface CancelSyncVariables {
  sourceId: string
  jobId: string
}

export function useCancelSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sourceId, jobId }: CancelSyncVariables) =>
      cancelSyncJobApi(sourceId, jobId),
    onSuccess: (_data, { sourceId }) => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.syncJobs(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.stats(sourceId) })
    },
  })
}

export function useRefreshDescription(sourceId: string) {
  return useMutation({
    mutationFn: () => refreshDescriptionApi(sourceId),
  })
}

export function useAutoNameSource(sourceId: string) {
  return useMutation({
    mutationFn: () => autoNameApi(sourceId),
  })
}

// ---------------------------------------------------------------------------
// Source intent (004-agentic-pipeline, T-025 review UI)
// ---------------------------------------------------------------------------

/**
 * Read a source's intent metadata (the six intent columns). Focused fetch for
 * the admin review surface — the same fields also ride on the source detail
 * payload, but IntentSection owns its own query so a propose/save invalidates
 * just this slice.
 */
export interface UseSourceIntentOptions {
  /**
   * FIX 2 — propose→GET staleness. After a successful propose (202) the worker
   * writes the new draft asynchronously; a single refetch races ahead of it.
   * When the caller sets this `true` (a regenerate is in flight), poll the
   * intent slice every 3s — mirroring `useSource`'s refetchInterval pattern —
   * until `intent_status` leaves `pending_ai` or a bounded number of polls
   * elapses, so the timer can never run forever if the worker stalls.
   */
  pollWhileRegenerating?: boolean
}

/** Stop polling after this many intervals even if the worker never lands. */
const INTENT_POLL_MAX = 10

export function useSourceIntent(
  sourceId: string | undefined,
  options: UseSourceIntentOptions = {}
) {
  const { pollWhileRegenerating = false } = options
  return useQuery<SourceIntent>({
    // FIX 1 — keep the disabled-state fallback key inside the sourcesKeys
    // hierarchy so a bulk `invalidateQueries({ queryKey: sourcesKeys.all })`
    // still matches it. `intent('')` shares the `['sources','intent']` prefix.
    queryKey: sourcesKeys.intent(sourceId ?? ''),
    queryFn: () => getIntentApi(sourceId as string),
    enabled: Boolean(sourceId),
    refetchInterval: pollWhileRegenerating
      ? (query) => {
          // The draft has landed once the status moves off pending_ai — stop.
          if (query.state.data?.intent_status !== 'pending_ai') return false
          // Bounded: give up after INTENT_POLL_MAX intervals so a stalled
          // worker can't leave the timer running indefinitely.
          if (query.state.dataUpdateCount >= INTENT_POLL_MAX) return false
          return 3_000
        }
      : false,
  })
}

/**
 * Admin save of source intent. Saving constitutes review: the server flips
 * `intent_status` → 'user_set' and the response carries the persisted bundle.
 * We seed that response into the cache and invalidate the source detail (whose
 * payload also embeds the intent fields) so the badge updates everywhere.
 *
 * A 422 (sanitization / cap violation) rejects with a problem+json Error; the
 * component surfaces the field-named message inline.
 */
export function useUpdateIntent(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SourceIntentUpdate) => putIntentApi(sourceId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(sourcesKeys.intent(sourceId), updated)
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
    },
  })
}

/**
 * (Re)generate the AI-proposed intent draft. The proposal runs async on the
 * worker; we invalidate the intent slice so a subsequent poll/refetch picks up
 * the new draft. A 409 (`IntentProposalConflictError`) means a study or
 * proposal is already in flight — the component shows a Sonner toast.
 */
export function useProposeIntent(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => proposeIntentApi(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.intent(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
    },
  })
}
