/**
 * Source lifecycle — shared phase derivation and gate matrix.
 *
 * U14/FX16: turn the implicit, scattered "is this source ready?" decisions on
 * the source-detail page into one named, testable state machine. Every
 * gating decision (Sync-now disabled? Chat tab disabled? Approve toggle
 * usable?) reads off the same `Phase` so the UI never disagrees with itself.
 *
 * The phase is purely derived from existing wire fields on
 * `SourceListItem` / `SourceDetail`. No new backend calls.
 *
 * ## Phases
 *
 * | Phase            | Meaning                                                    |
 * |------------------|------------------------------------------------------------|
 * | `pending_upload` | A file source was created but no bytes landed yet.         |
 * | `naming`         | AI is drafting name / description (post-upload, pre-sync). |
 * | `chunking`       | Ingestion job is running, chunks not yet produced.         |
 * | `analyzing`      | Chunks produced; finalizing index / schema description.    |
 * | `ready`          | Documented, has chunks, no in-flight job — usable.         |
 * | `failed`         | Latest ingestion or study job ended in error.              |
 *
 * The mapping is documented inline in `derivePhase` and matches the gate
 * matrix in `lifecycleGatesFor`.
 */

import type { SourceDetail, SourceListItem } from '@/lib/api/sources'

// ---------------------------------------------------------------------------
// Phase enum + UX metadata
// ---------------------------------------------------------------------------

export type Phase =
  | 'pending_upload'
  | 'naming'
  | 'chunking'
  | 'analyzing'
  | 'ready'
  | 'failed'

/** Stable order used by the Stepper component. `failed` is rendered as a tone
 * on the otherwise-active step, not as a separate cell. */
export const PHASE_ORDER: ReadonlyArray<Exclude<Phase, 'failed'>> = [
  'pending_upload',
  'naming',
  'chunking',
  'analyzing',
  'ready',
] as const

/** Display label used in chips and progress bars. */
export function phaseLabel(phase: Phase): string {
  switch (phase) {
    case 'pending_upload':
      return 'Waiting for upload'
    case 'naming':
      return 'Naming with AI'
    case 'chunking':
      return 'Chunking content'
    case 'analyzing':
      return 'Analyzing & indexing'
    case 'ready':
      return 'Ready'
    case 'failed':
      return 'Failed'
  }
}

/**
 * Approximate 0–100 progress for the phase. Used for the linear progress bar
 * fill where we don't have a real percent from the worker. Returns `-1` for
 * phases that should render indeterminate (the bar shows an animated stripe
 * rather than a fill).
 */
export function phaseProgress(phase: Phase): number {
  switch (phase) {
    case 'pending_upload':
      return 5
    case 'naming':
      return 25
    case 'chunking':
      return 55
    case 'analyzing':
      return 85
    case 'ready':
      return 100
    case 'failed':
      return 0
  }
}

/** Should the progress bar render at all? */
export function isInFlightPhase(phase: Phase): boolean {
  return (
    phase === 'pending_upload' ||
    phase === 'naming' ||
    phase === 'chunking' ||
    phase === 'analyzing'
  )
}

/**
 * Should the source-detail query keep polling on a 3s tick? Distinct from
 * `isInFlightPhase` only because `pending_upload` is a quiet state where
 * nothing is going to change without a user action.
 */
export function isPollingPhase(phase: Phase): boolean {
  return phase === 'naming' || phase === 'chunking' || phase === 'analyzing'
}

// ---------------------------------------------------------------------------
// derivePhase
// ---------------------------------------------------------------------------

type SourceLike = SourceListItem | SourceDetail

function chunkCountOf(source: SourceLike): number {
  if (typeof source.chunk_count === 'number') return source.chunk_count
  return source.latest_job?.chunks_created ?? 0
}

function isFileSource(source: SourceLike): boolean {
  // The backend StrEnum emits `file_upload`; older fixtures and the
  // forward-compat extras (`pdf`, `docx`, etc.) all behave the same way.
  const t = source.source_type
  return (
    t === 'file_upload' ||
    t === 'pdf' ||
    t === 'docx' ||
    t === 'xlsx' ||
    t === 'csv' ||
    t === 'txt' ||
    t === 'markdown'
  )
}

/**
 * Compute the source's lifecycle phase from the cached wire data. Pure — safe
 * to call on every render.
 *
 * Detection order matters: failures dominate, then schema-study state (for DB
 * sources), then in-flight ingestion, then AI naming, then steady states.
 */
export function derivePhase(source: SourceLike): Phase {
  const job = source.latest_job ?? null
  const jobStatus = job?.status ?? null

  // 1. Terminal failure on the last run beats everything else. A `failed` job
  //    plus a still-pending name is still "failed" from the user's POV.
  if (jobStatus === 'failed') return 'failed'
  if (source.schema_status === 'FAILED') return 'failed'

  // 2. DB-source studying agent is its own ingestion path. When the studying
  //    agent is active, we surface it as `analyzing` (schema study =
  //    analyzing the database).
  if (
    source.schema_status === 'STUDYING' ||
    source.schema_status === 'QUEUED'
  ) {
    return 'analyzing'
  }

  // 3. AI naming/description pending — render the "naming" phase only when
  //    we have no other forward-progress signal. Both `naming` and
  //    `analyzing` gate availability via the same gate matrix, so the
  //    progress-bar fidelity wins: if a job is running and chunks are
  //    growing, prefer `analyzing` (85%) over `naming` (25%) so the bar
  //    doesn't appear stuck while the worker is clearly further along.
  const namePending = source.name_status === 'pending_ai'
  const descPending = source.description_status === 'pending_ai'
  if (namePending || descPending) {
    if (jobStatus === 'running' && chunkCountOf(source) > 0) {
      return 'analyzing'
    }
    return 'naming'
  }

  // 4. In-flight ingestion job — split into chunking vs analyzing based on
  //    whether any chunks have landed yet. Chunks growing → analyzing
  //    (finalizing index); zero chunks → chunking (still extracting).
  if (jobStatus === 'running') {
    return chunkCountOf(source) > 0 ? 'analyzing' : 'chunking'
  }

  // 5. Queued job — pending_upload for file sources without bytes, otherwise
  //    "chunking" (queued for the worker to pick up).
  if (jobStatus === 'pending') {
    if (isFileSource(source) && source.has_upload === false) {
      return 'pending_upload'
    }
    return 'chunking'
  }

  // 6. No job recorded at all. File sources without bytes are pending upload.
  //    A source the backend has already promoted to status==='ready' (or that
  //    has accumulated chunks / last_synced_at) is treated as ready — the
  //    backend's own status flag wins over the absence of a job record.
  if (jobStatus === null) {
    if (isFileSource(source) && source.has_upload === false) {
      return 'pending_upload'
    }
    if (source.status === 'ready') {
      return 'ready'
    }
    if (chunkCountOf(source) === 0 && !source.last_synced_at) {
      return 'pending_upload'
    }
    return 'ready'
  }

  // 7. Terminal success — ready iff we actually have chunks (or, for DB
  //    sources, the schema is documented). An empty success is treated as
  //    `ready` so the admin can re-sync; we don't have a separate "empty"
  //    bucket in this phase taxonomy.
  if (jobStatus === 'success' || jobStatus === 'completed') {
    return 'ready'
  }

  // Defensive fallback — never lock out the UI forever.
  return 'ready'
}

// ---------------------------------------------------------------------------
// Gate matrix
// ---------------------------------------------------------------------------

export interface LifecycleGates {
  /** Can the admin trigger a new sync / re-study? */
  canSyncNow: boolean
  /** Reason the sync action is disabled (for tooltips). Empty when enabled. */
  syncNowReason: string

  /** Can the admin send messages in the Test (sandbox) tab? */
  canChat: boolean
  /** Reason chat is disabled. */
  chatReason: string

  /** Can the admin flip the "Available to users" switch on? */
  canMakeAvailableToUsers: boolean
  /** Reason availability toggle is disabled. */
  availabilityReason: string

  /** Settings form mutations — always allowed even mid-ingestion. */
  canEditConfig: boolean
}

/**
 * Static gate matrix from `Phase` only. Most controls collapse to the same
 * "is the source quiet?" question. We expose them as separate booleans so
 * callers don't have to remember which one to use.
 *
 * Note: the AVAILABILITY gate is the AND of `phase === 'ready'` AND the
 * existing naming/description guards on the Settings page. The naming guard
 * lives in `availabilityBlockers` below.
 */
export function lifecycleGatesFor(phase: Phase): LifecycleGates {
  const inFlight =
    phase === 'pending_upload' ||
    phase === 'naming' ||
    phase === 'chunking' ||
    phase === 'analyzing'

  if (phase === 'failed') {
    return {
      canSyncNow: true,
      syncNowReason: '',
      canChat: false,
      chatReason: "Last run failed — retry sync before testing this source.",
      canMakeAvailableToUsers: false,
      availabilityReason:
        'Cannot approve a source whose last ingestion run failed. Retry first.',
      canEditConfig: true,
    }
  }

  if (inFlight) {
    const verb =
      phase === 'pending_upload'
        ? 'finish uploading the files'
        : phase === 'naming'
          ? 'finish drafting the name'
          : phase === 'chunking'
            ? 'finish chunking the content'
            : 'finish indexing'
    return {
      canSyncNow: false,
      syncNowReason: `Wait for the worker to ${verb}.`,
      canChat: false,
      chatReason: `Wait for the worker to ${verb}. Chat is available once the source is ready.`,
      canMakeAvailableToUsers: false,
      availabilityReason: `Wait for the worker to ${verb} before approving the source for users.`,
      canEditConfig: true,
    }
  }

  // phase === 'ready'
  return {
    canSyncNow: true,
    syncNowReason: '',
    canChat: true,
    chatReason: '',
    canMakeAvailableToUsers: true,
    availabilityReason: '',
    canEditConfig: true,
  }
}

// ---------------------------------------------------------------------------
// Approval blockers (composed with the phase gate)
// ---------------------------------------------------------------------------

/**
 * Naming/description prerequisites for "Available to users" — these are
 * stricter than the phase gate. A source can be in `ready` phase yet still
 * have an empty description, which fails approval per PRD §11.
 *
 * Returns an empty array when the source is approvable; each string is a
 * human-readable blocker the UI can render in a callout.
 */
export function availabilityBlockers(source: SourceLike): string[] {
  const blockers: string[] = []
  if (source.name_status === 'pending_ai') {
    blockers.push(
      'AI naming has not finished — wait for "Naming…" to clear, or type a name in Settings.'
    )
  }
  if (source.description_status === 'pending_ai') {
    blockers.push('AI description has not finished — wait for it to clear.')
  }
  const description = ('description' in source ? source.description : null) ?? ''
  const descMissing = description.trim().length === 0
  if (descMissing && source.description_status !== 'pending_ai') {
    blockers.push(
      'Description is empty — write one in Settings, or use "Regenerate description" in the AI naming assistant.'
    )
  }
  return blockers
}

// ---------------------------------------------------------------------------
// React hook wrapper
// ---------------------------------------------------------------------------

/**
 * Convenience hook that derives the phase and the gate matrix in one call.
 * Components that need a single answer ("is this control enabled?") should
 * destructure off the returned object.
 *
 * Re-derived on every render — `derivePhase` is O(1) and React Query already
 * memoises the source object reference across cache hits, so any naive memo
 * here would be more code than it's worth.
 */
export interface UseLifecycleResult extends LifecycleGates {
  phase: Phase
  /** Naming/description-aware approval blockers, in addition to the phase gate. */
  approvalBlockers: string[]
  /** Composite gate — phase allows it AND there are no approval blockers. */
  canApproveNow: boolean
}

export function useLifecycle(source: SourceLike | null | undefined): UseLifecycleResult {
  // Safe fallback for the loading state — surface "naming" so every gate
  // stays disabled. Callers should still gate on `isLoading` from the query,
  // but this prevents a flash of enabled controls if the data is briefly
  // undefined.
  if (!source) {
    const phase: Phase = 'naming'
    const gates = lifecycleGatesFor(phase)
    return {
      phase,
      ...gates,
      approvalBlockers: [],
      canApproveNow: false,
    }
  }
  const phase = derivePhase(source)
  const gates = lifecycleGatesFor(phase)
  const approvalBlockers = availabilityBlockers(source)
  return {
    phase,
    ...gates,
    approvalBlockers,
    canApproveNow:
      gates.canMakeAvailableToUsers && approvalBlockers.length === 0,
  }
}
