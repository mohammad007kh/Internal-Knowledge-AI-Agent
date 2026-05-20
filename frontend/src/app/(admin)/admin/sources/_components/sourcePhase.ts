import type { SourceListItem } from '@/lib/api/sources'

/**
 * `Phase` is a derived state of a source row, computed purely from the existing
 * fields on `SourceListItem`. No additional backend calls are required.
 *
 * The "Next step" column in the admin sources table renders one verb per row
 * based on this phase. See `derivePhase` for the detection rules.
 */
export type Phase =
  | 'awaiting_approval'
  | 'queued'
  | 'running'
  | 'ready'
  | 'failed'
  | 'empty'
  | 'unknown'

/**
 * Read the chunk count from a list item. The list response does not expose
 * `chunk_count` directly, so we use the latest job's `chunks_created` as the
 * canonical signal — it is the same number the detail page would show.
 */
function chunkCount(source: Readonly<SourceListItem>): number {
  return source.latest_job?.chunks_created ?? 0
}

/**
 * Derive the row's current phase from existing fields. Pure function — safe to
 * call on every render.
 *
 * | Phase                | Detection                                                            |
 * |----------------------|----------------------------------------------------------------------|
 * | `awaiting_approval`  | `is_active === false` AND (no job OR job is `pending`)               |
 * | `queued`             | `is_active === true`  AND (no job OR job is `pending`)               |
 * | `running`            | `latest_job.status === 'running'`                                    |
 * | `ready`              | `latest_job.status === 'success'` AND chunks > 0                     |
 * | `failed`             | `latest_job.status === 'failed'`                                     |
 * | `empty`              | `latest_job.status === 'success'` AND chunks === 0                   |
 * | `unknown`            | Any combination not matched above (defensive fallback)               |
 */
export function derivePhase(source: Readonly<SourceListItem>): Phase {
  const job = source.latest_job
  const jobStatus = job?.status ?? null

  // Highest-priority terminal states from the latest job.
  if (jobStatus === 'running') return 'running'
  if (jobStatus === 'failed') return 'failed'

  if (jobStatus === 'success' || jobStatus === 'completed') {
    return chunkCount(source) > 0 ? 'ready' : 'empty'
  }

  // No job yet, or the only job is `pending` — split on admin approval.
  const noProgress = job === null || job === undefined || jobStatus === 'pending'
  if (noProgress) {
    return source.is_active ? 'queued' : 'awaiting_approval'
  }

  return 'unknown'
}
