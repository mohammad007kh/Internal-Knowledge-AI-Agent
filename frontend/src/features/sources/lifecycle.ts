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

import {
  type SourceKind,
  sourceKindOf,
} from '@/app/(admin)/admin/sources/[id]/_components/sourceTypeMatrix'
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

/** Re-exported so callers can write `import { SourceKind } from
 * '@/features/sources/lifecycle'` without dipping into the route-private
 * `_components/sourceTypeMatrix` path. The canonical definition lives in
 * sourceTypeMatrix — this is just a passthrough. */
export type { SourceKind } from '@/app/(admin)/admin/sources/[id]/_components/sourceTypeMatrix'

/** Stable order used by the Stepper component for file/web/connector sources.
 * `failed` is rendered as a tone on the otherwise-active step, not as a
 * separate cell. DB sources omit `chunking` entirely — they have no documents
 * to chunk; see `phaseOrderFor`. Kept exported for back-compat with the few
 * call sites (LifecycleProgressBar, lifecycle tests) that walk every phase
 * regardless of source kind. */
export const PHASE_ORDER: ReadonlyArray<Exclude<Phase, 'failed'>> = [
  'pending_upload',
  'naming',
  'chunking',
  'analyzing',
  'ready',
] as const

/** Phase order for the DB stepper. DB sources never enter `chunking` per
 * `derivePhase`'s rule 2 (schema_status STUDYING → analyzing directly), so
 * showing the chunking chip would be a dead step the worker can never reach. */
const PHASE_ORDER_DATABASE: ReadonlyArray<Exclude<Phase, 'failed'>> = [
  'pending_upload',
  'naming',
  'analyzing',
  'ready',
] as const

/**
 * Per-source-kind phase order for the Stepper. File / web / connector all
 * share the same 5-chip strip; databases drop the chunking chip.
 */
export function phaseOrderFor(
  kind: SourceKind
): ReadonlyArray<Exclude<Phase, 'failed'>> {
  if (kind === 'database') return PHASE_ORDER_DATABASE
  // file, web, connector — all five chips.
  return PHASE_ORDER
}

// ---------------------------------------------------------------------------
// Per-source-kind label + hint tables
//
// FX23: the original phaseLabel was source-agnostic ("Waiting for upload" for
// every source) which is nonsense for DB and web sources. We index labels by
// `(phase, kind)` so the stepper shows what the worker is actually doing for
// each kind:
//
//   • file       — upload → naming → chunking → analyzing → ready
//   • database   — queued → naming → studying schema → ready
//   • web        — queued → naming → crawling → analyzing → ready
//   • connector  — same shape as web
//
// connectors mirror the web labels because SaaS connectors (Confluence,
// Notion, etc.) all behave like crawlers from the user's POV.
// ---------------------------------------------------------------------------

type LabelTable = Record<Phase, string>

const FILE_LABELS: LabelTable = {
  pending_upload: 'Waiting for upload',
  naming: 'Naming with AI',
  chunking: 'Chunking content',
  analyzing: 'Analyzing & indexing',
  ready: 'Ready',
  failed: 'Failed',
}

const DATABASE_LABELS: LabelTable = {
  pending_upload: 'Queued',
  naming: 'Naming with AI',
  // `chunking` is dropped from the DB stepper but the label has to exist for
  // type completeness. If we ever did land in `chunking` for a DB source it
  // would be a bug — surface a neutral label so we don't crash, but never
  // show this label in the normal stepper render.
  chunking: 'Chunking content',
  analyzing: 'Studying schema',
  ready: 'Ready',
  failed: 'Failed',
}

const WEB_LABELS: LabelTable = {
  pending_upload: 'Queued',
  naming: 'Naming with AI',
  chunking: 'Crawling content',
  analyzing: 'Analyzing & indexing',
  ready: 'Ready',
  failed: 'Failed',
}

// Connectors share the web labels — SaaS connectors are crawler-style.
const CONNECTOR_LABELS: LabelTable = WEB_LABELS

const LABELS_BY_KIND: Record<SourceKind, LabelTable> = {
  file: FILE_LABELS,
  database: DATABASE_LABELS,
  web: WEB_LABELS,
  connector: CONNECTOR_LABELS,
}

type HintTable = Record<Exclude<Phase, 'failed'>, string>

const FILE_HINTS: HintTable = {
  pending_upload: 'Files are landing in object storage.',
  naming: 'The AI is drafting a name and description.',
  chunking: 'Splitting the content into retrieval-friendly chunks.',
  analyzing: 'Embedding chunks and finalizing the index.',
  ready: 'This source is ready to query.',
}

const DATABASE_HINTS: HintTable = {
  pending_upload: 'Sync queued — waiting for a worker.',
  naming: 'The AI is drafting a name and description.',
  // See note on DATABASE_LABELS.chunking — never rendered in normal flow.
  chunking: 'Splitting the content into retrieval-friendly chunks.',
  analyzing:
    'The studying agent is cataloguing tables + sampling columns.',
  ready: 'This source is ready to query.',
}

const WEB_HINTS: HintTable = {
  pending_upload: 'Sync queued — waiting for a worker.',
  naming: 'The AI is drafting a name and description.',
  chunking: 'Crawling pages from the URL.',
  analyzing: 'Embedding chunks and finalizing the index.',
  ready: 'This source is ready to query.',
}

const CONNECTOR_HINTS: HintTable = WEB_HINTS

const HINTS_BY_KIND: Record<SourceKind, HintTable> = {
  file: FILE_HINTS,
  database: DATABASE_HINTS,
  web: WEB_HINTS,
  connector: CONNECTOR_HINTS,
}

/**
 * Display label used in chips and progress bars.
 *
 * The `kind` parameter defaults to `'file'` so older call sites that haven't
 * been migrated (eg LifecycleProgressBar, which U16 still owns) keep the
 * existing file-centric labels — no behavioural change for them.
 *
 * FX26: `opts.hasUpload` retunes the file-source `pending_upload` label.
 * Once the upload is on object storage the "Waiting for upload" copy is
 * actively misleading — the upload IS done, we're just queued for the
 * worker to pick it up. Switch to "Queued for indexing" so the user reads
 * the actual state. Same `Phase` enum + same gate matrix — only the
 * display string changes, so existing tests and the rest of the state
 * machine are untouched.
 */
export interface PhaseLabelOptions {
  /** True when a file-typed source has bytes in object storage. */
  hasUpload?: boolean
}

export function phaseLabel(
  phase: Phase,
  kind: SourceKind = 'file',
  opts: PhaseLabelOptions = {}
): string {
  if (
    phase === 'pending_upload' &&
    kind === 'file' &&
    opts.hasUpload === true
  ) {
    return 'Queued for indexing'
  }
  return LABELS_BY_KIND[kind][phase]
}

/**
 * Hint string shown in the Stepper tooltip while a step is active.
 *
 * `failed` has no hint of its own — the StepChip composes a "Failed during
 * {label}" string at render time, so this table only covers in-flight + ready
 * phases. Defaults to `'file'` for the same back-compat reason as
 * `phaseLabel`.
 *
 * FX26: mirrors the file-source `pending_upload` label switch — once the
 * upload is on object storage the "Files are landing…" copy is misleading,
 * so we surface "Files uploaded — queued for the indexing worker." instead.
 * Same signature as `phaseLabel`'s opts so call sites can pass the
 * has_upload flag through identically.
 */
export function phaseHint(
  phase: Exclude<Phase, 'failed'>,
  kind: SourceKind = 'file',
  opts: PhaseLabelOptions = {}
): string {
  if (
    phase === 'pending_upload' &&
    kind === 'file' &&
    opts.hasUpload === true
  ) {
    return 'Files uploaded — queued for the indexing worker.'
  }
  return HINTS_BY_KIND[kind][phase]
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
  // U16 — `cancelled` is a fifth SyncJob terminal state; collapse into
  // `failed` for phase-derivation purposes. The gate matrix's `failed` row
  // already says "retry sync before testing this source", which is exactly
  // the right copy after a stop. We deliberately do NOT add a separate
  // `cancelled` Phase: every gate decision would be identical, and a sixth
  // phase would just double the test surface.
  if (jobStatus === 'cancelled') return 'failed'
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

  // 2b. FX32 — DB-source studying agent terminal success. DB sources don't
  //     produce chunks, don't set `last_synced_at`, and don't create a
  //     `sync_job` row when study_source runs directly (POST /sources for
  //     type=database). Without this early return, a completed DB study
  //     lands in rule-6's `latest_job === null` fallback, fails the
  //     chunk_count + last_synced_at check, and pins at `pending_upload`
  //     forever — locking the admin out of the approval gate.
  //
  //     The studying agent IS what makes a DB source "ready". Schema
  //     status `'completed'` (lowercase — that's what
  //     SourceRepository.set_schema_status writes) is the canonical signal.
  //
  //     Defensive guard: skip when a non-terminal sync_job is in flight
  //     so a re-study (which creates a pending/running sync_job whose
  //     task then flips schema_status back to 'studying') doesn't briefly
  //     read as `ready` during the race between the API row landing and
  //     the worker stamping 'studying'. Once schema_status flips, rule 2
  //     takes over and surfaces `analyzing`.
  if (
    source.source_type === 'database' &&
    // SchemaStatus is typed as the legacy uppercase tokens ('READY' | 'STALE')
    // but the wire actually carries the lowercase strings the backend writes
    // ('completed' | 'studying' | 'failed' | …). The type drift is broader
    // than this rule — cast through `string` to keep the comparison readable
    // and avoid an out-of-scope type-widening here. (FX32b)
    (source.schema_status as string | null | undefined) === 'completed' &&
    jobStatus !== 'pending' &&
    jobStatus !== 'running'
  ) {
    return 'ready'
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

  /**
   * U16 — Can the admin stop an in-flight sync? True iff the source has a
   * non-terminal `latest_job` (pending or running). Mutually exclusive with
   * `canSyncNow` in normal flows: while the source is mid-ingestion the
   * "Sync now" affordance is replaced by "Stop sync".
   *
   * Computed from the SOURCE rather than the Phase enum because `naming`
   * can exist without a job. `lifecycleGatesFor(phase)` returns `false` —
   * the `useLifecycle` hook fills in the real value from `latest_job`.
   */
  canStopSync: boolean

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
 * Per-source-kind in-flight verb table for the gate-matrix copy (FX29b).
 *
 * Before FX29b the gate matrix hard-coded file-pipeline language ("finish
 * uploading the files", "finish chunking the content") for every source
 * type. A web_url source in `pending_upload` would surface "Wait for the
 * worker to finish uploading the files" — confusing because there is no
 * upload, the worker is queueing the initial crawl.
 *
 * The `file` row preserves the U14/FX16 strings byte-for-byte so the
 * existing tests stay green; web / connector / database get verbs that
 * match what the worker is actually doing:
 *
 *   • file       — upload → chunking → indexing
 *   • web/connector — queueing crawl → crawling → indexing
 *   • database   — queueing schema study → studying schema (chunking
 *     is defensive only; DB sources skip the chunking phase in
 *     derivePhase but the table needs the slot for type completeness).
 */
type InFlightPhase = Exclude<Phase, 'failed' | 'ready'>

const IN_FLIGHT_VERBS: Record<SourceKind, Record<InFlightPhase, string>> = {
  file: {
    pending_upload: 'finish uploading the files',
    naming: 'finish drafting the name',
    chunking: 'finish chunking the content',
    analyzing: 'finish indexing',
  },
  web: {
    pending_upload: 'finish queueing the initial crawl',
    naming: 'finish drafting the name',
    chunking: 'finish crawling the pages',
    analyzing: 'finish indexing',
  },
  connector: {
    // SaaS connectors (Confluence, SharePoint, Notion, …) are crawler-style
    // from the user's POV — mirror the web verbs.
    pending_upload: 'finish queueing the initial crawl',
    naming: 'finish drafting the name',
    chunking: 'finish crawling the pages',
    analyzing: 'finish indexing',
  },
  database: {
    pending_upload: 'finish queueing the schema study',
    naming: 'finish drafting the name',
    // Defensive — derivePhase routes DB sources straight from `naming`
    // (or `pending_upload`) to `analyzing`, so `chunking` should never
    // be observed for a DB source. The verb only exists for type
    // completeness; if it ever surfaces it should still read like
    // schema-study language rather than file/crawler copy.
    chunking: 'finish studying the schema',
    analyzing: 'finish studying the schema',
  },
}

/**
 * Static gate matrix from `Phase` (+ optional source `kind`). Most controls
 * collapse to the same "is the source quiet?" question. We expose them as
 * separate booleans so callers don't have to remember which one to use.
 *
 * The `kind` parameter defaults to `'file'` so older call sites that
 * haven't been migrated keep the existing file-centric copy — no
 * behavioural change for them (FX29b).
 *
 * Note: the AVAILABILITY gate is the AND of `phase === 'ready'` AND the
 * existing naming/description guards on the Settings page. The naming guard
 * lives in `availabilityBlockers` below.
 */
export function lifecycleGatesFor(
  phase: Phase,
  kind: SourceKind = 'file'
): LifecycleGates {
  const inFlight =
    phase === 'pending_upload' ||
    phase === 'naming' ||
    phase === 'chunking' ||
    phase === 'analyzing'

  if (phase === 'failed') {
    return {
      canSyncNow: true,
      syncNowReason: '',
      canStopSync: false,
      canChat: false,
      chatReason: "Last run failed — retry sync before testing this source.",
      canMakeAvailableToUsers: false,
      availabilityReason:
        'Cannot approve a source whose last ingestion run failed. Retry first.',
      canEditConfig: true,
    }
  }

  if (inFlight) {
    const verb = IN_FLIGHT_VERBS[kind][phase as InFlightPhase]
    return {
      canSyncNow: false,
      syncNowReason: `Wait for the worker to ${verb}.`,
      // Phase-only callers can't know whether there's a real in-flight
      // SyncJob to stop (naming can exist without a job). `useLifecycle`
      // upgrades this to the real answer from `latest_job.status`.
      canStopSync: false,
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
    canStopSync: false,
    canChat: true,
    chatReason: '',
    canMakeAvailableToUsers: true,
    availabilityReason: '',
    canEditConfig: true,
  }
}

// ---------------------------------------------------------------------------
// U16 — stop-sync target. What job_id should the cancel mutation POST against?
// ---------------------------------------------------------------------------

/**
 * Returns the latest job iff it's non-terminal (`pending` or `running`),
 * otherwise `null`. Callers gate the Stop button on this returning truthy
 * AND on `canStopSync` from the gate matrix — both must agree.
 */
export function stopSyncTargetJobId(
  source: SourceLike | null | undefined
): string | null {
  const job = source?.latest_job ?? null
  if (!job) return null
  if (job.status === 'pending' || job.status === 'running') {
    return job.id
  }
  return null
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
  // undefined. `kind` is unknown here; the default 'file' keeps the legacy
  // copy ("finish drafting the name") — fine because we don't know the
  // kind yet.
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
  // FX29b — derive the kind from the wire source_type so the gate-matrix
  // copy ("Wait for the worker to …") matches the actual pipeline (web →
  // crawl verbs, database → schema-study verbs).
  const kind = sourceKindOf(source.source_type)
  const gates = lifecycleGatesFor(phase, kind)
  const approvalBlockers = availabilityBlockers(source)
  // U16 — upgrade the phase-only `canStopSync` to the source-aware answer.
  // The Stop button is only safe to show when there is a real non-terminal
  // job for the backend to cancel; the gate matrix's default `false` is
  // the safe baseline.
  const canStopSync = stopSyncTargetJobId(source) !== null
  return {
    phase,
    ...gates,
    canStopSync,
    approvalBlockers,
    canApproveNow:
      gates.canMakeAvailableToUsers && approvalBlockers.length === 0,
  }
}
