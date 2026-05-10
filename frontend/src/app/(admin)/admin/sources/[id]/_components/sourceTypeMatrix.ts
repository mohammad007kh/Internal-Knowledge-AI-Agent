/**
 * Per-source-type form gating + relabeling helpers.
 *
 * The Settings form, the Documents tab label, and a handful of copy strings
 * across the detail page all branch on `source_type`. Centralizing the
 * decisions here keeps the page lean and gives tests one place to verify the
 * matrix when product asks "for a Postgres source, can the admin still pick
 * vector_only?" (answer: no — locked to text_to_query).
 */
import type { SourceType, SyncMode } from '@/lib/api/sources'

/**
 * Coarse "kind" of a source — files, web pages, databases, or SaaS connectors.
 * Three cards' worth of wiring boil down to four answers, so we collapse the
 * 16-value `SourceType` enum to four kinds at the boundary and branch off
 * the kind in the UI.
 */
export type SourceKind = 'file' | 'web' | 'database' | 'connector'

const DB_TYPES: ReadonlySet<SourceType> = new Set<SourceType>([
  'postgresql',
  'mysql',
  'mssql',
  'mongodb',
])

const FILE_TYPES: ReadonlySet<SourceType> = new Set<SourceType>([
  'pdf',
  'docx',
  'xlsx',
  'csv',
  'txt',
  'markdown',
  'file_upload',
])

const CONNECTOR_TYPES: ReadonlySet<SourceType> = new Set<SourceType>([
  'confluence',
  'sharepoint',
  'google_drive',
  'notion',
])

export function sourceKindOf(sourceType: SourceType): SourceKind {
  if (DB_TYPES.has(sourceType)) return 'database'
  if (FILE_TYPES.has(sourceType)) return 'file'
  if (CONNECTOR_TYPES.has(sourceType)) return 'connector'
  // `web_url` and any unknown future type fall through to web.
  return 'web'
}

/**
 * Per-type label for the second tab on the source detail page.
 *
 * We picked "Schema" over "Tables" for DB sources so the tab label maps
 * cleanly onto the studying-agent's mental model — the agent produces a
 * single SchemaDocument, not "tables" the admin browses.
 */
export function dataTabLabelFor(sourceType: SourceType): string {
  switch (sourceKindOf(sourceType)) {
    case 'file':
      return 'Files'
    case 'database':
      return 'Schema'
    case 'web':
    case 'connector':
      return 'Pages'
  }
}

/**
 * Per-type singular noun for inline copy. Plural is just `${noun}s`.
 *
 * Used by the Overview cards and Documents tab when the previous copy
 * said "documents" generically. e.g. "12 pages crawled" instead of
 * "12 documents indexed" for a web source.
 */
export function dataNounFor(
  sourceType: SourceType,
  count: 'one' | 'other' = 'other'
): string {
  const kind = sourceKindOf(sourceType)
  if (kind === 'database') return count === 'one' ? 'table' : 'tables'
  if (kind === 'file') return count === 'one' ? 'file' : 'files'
  return count === 'one' ? 'page' : 'pages'
}

/**
 * Empty-state copy for the Documents tab — what to tell the admin when
 * the per-type list is empty.
 */
export function emptyDataCopyFor(sourceType: SourceType): string {
  switch (sourceKindOf(sourceType)) {
    case 'file':
      return 'No files uploaded yet.'
    case 'database':
      return 'No tables documented yet. Click Re-study schema to start.'
    case 'web':
      return 'No pages crawled yet.'
    case 'connector':
      return 'No pages indexed yet.'
  }
}

// ---------------------------------------------------------------------------
// Settings form gating matrix
// ---------------------------------------------------------------------------

/**
 * What the Settings form should show for a given source type.
 *
 * `retrieval_mode` and `source_mode` are operationally unsafe to flip
 * post-creation for most types — for DB sources they're effectively locked
 * to (`text_to_query`, `live`) and for everything else they're hidden so
 * the admin can't break ingestion by clicking around. For `database` we
 * surface them as read-only chips with a tooltip explaining why.
 *
 * `sync_mode` is the only bit of polymorphism: file sources can't do
 * delta sync (no upstream change feed), DBs in `live` mode don't sync at
 * all (no documents), DBs in `snapshot` mode behave like file sources.
 */
export interface FormFieldConfig {
  /** Whether to render the retrieval_mode field, and if so, in what shape. */
  retrievalMode: 'edit' | 'readonly-chip' | 'hidden'
  /** Whether to render the source_mode field, and if so, in what shape. */
  sourceMode: 'edit' | 'readonly-chip' | 'hidden'
  /**
   * Allowed sync_mode options. Empty array → field hidden entirely (e.g.
   * DB live source — no sync to schedule).
   */
  syncModeOptions: ReadonlyArray<SyncMode>
}

export interface GetEditableFieldsArgs {
  sourceType: SourceType
  /** Current `source_mode` — used because the DB sync_mode visibility depends on it. */
  sourceMode: 'snapshot' | 'live'
}

export function getEditableFieldsFor({
  sourceType,
  sourceMode,
}: GetEditableFieldsArgs): FormFieldConfig {
  const kind = sourceKindOf(sourceType)
  if (kind === 'database') {
    return {
      retrievalMode: 'readonly-chip',
      sourceMode: 'readonly-chip',
      syncModeOptions: sourceMode === 'live' ? [] : ['manual', 'scheduled'],
    }
  }
  if (kind === 'file') {
    return {
      retrievalMode: 'hidden',
      sourceMode: 'hidden',
      // Files have no upstream change feed → no delta. PDFs/etc. are
      // re-uploaded wholesale, so `manual` and `scheduled` are it.
      syncModeOptions: ['manual', 'scheduled'],
    }
  }
  if (kind === 'web') {
    return {
      retrievalMode: 'hidden',
      sourceMode: 'hidden',
      // Web crawlers can do delta (sitemap diff / lastmod tracking).
      syncModeOptions: ['manual', 'scheduled', 'delta'],
    }
  }
  // Connector — same shape as web; SaaS connectors generally support delta.
  return {
    retrievalMode: 'hidden',
    sourceMode: 'hidden',
    syncModeOptions: ['manual', 'scheduled', 'delta'],
  }
}
