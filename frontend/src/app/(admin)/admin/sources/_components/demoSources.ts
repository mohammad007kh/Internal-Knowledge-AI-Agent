/**
 * Mocked DB-source rows that exercise every (`schema_status` × `study_state`)
 * combination. Activated on `/admin/sources?demo=db-states` so admins can
 * review the new `DatabaseStudyStrip` + `SourceActionCell` visuals BEFORE
 * Wave 3 wires the real columns onto the API payload.
 *
 * Do NOT import this anywhere outside the sources admin page or its tests.
 */

import type { SourceListItem } from '@/lib/api/sources'

const NOW = '2026-05-09T12:00:00Z'

function makeRow(
  overrides: Partial<SourceListItem> & Pick<SourceListItem, 'id' | 'name'>
): SourceListItem {
  return {
    source_type: 'postgresql',
    is_active: false,
    created_at: NOW,
    source_mode: 'snapshot',
    sync_mode: 'manual',
    last_synced_at: null,
    description: null,
    latest_job: null,
    schema_status: null,
    study_state: null,
    tables_documented: null,
    tables_partial: null,
    last_error_phase: null,
    last_error_message: null,
    ...overrides,
  }
}

export const DEMO_DB_SOURCES: readonly SourceListItem[] = [
  // 1) Brand new — never approved.
  makeRow({
    id: 'demo-db-new',
    name: 'Sales replica (just added)',
  }),
  // 2) Approved & queued for study.
  makeRow({
    id: 'demo-db-queued',
    name: 'Sales replica (queued)',
    is_active: true,
    schema_status: 'QUEUED',
    study_state: 'QUEUED',
  }),
  // 3) Studying — connecting.
  makeRow({
    id: 'demo-db-connecting',
    name: 'Warehouse (connecting)',
    is_active: true,
    schema_status: 'STUDYING',
    study_state: 'CONNECTING',
  }),
  // 4) Studying — listing tables.
  makeRow({
    id: 'demo-db-inventory',
    name: 'Warehouse (listing tables)',
    is_active: true,
    schema_status: 'STUDYING',
    study_state: 'INVENTORY',
  }),
  // 5) Studying — sampling rows.
  makeRow({
    id: 'demo-db-sampling',
    name: 'Warehouse (sampling rows)',
    is_active: true,
    schema_status: 'STUDYING',
    study_state: 'SAMPLING',
    tables_documented: 12,
  }),
  // 6) Studying — describing with AI.
  makeRow({
    id: 'demo-db-describing',
    name: 'CRM (describing with AI)',
    is_active: true,
    schema_status: 'STUDYING',
    study_state: 'DESCRIBING',
    tables_documented: 28,
  }),
  // 7) Studying — indexing.
  makeRow({
    id: 'demo-db-indexing',
    name: 'CRM (indexing schema)',
    is_active: true,
    schema_status: 'STUDYING',
    study_state: 'INDEXING',
    tables_documented: 28,
  }),
  // 8) Ready, not yet approved.
  makeRow({
    id: 'demo-db-ready-pending',
    name: 'Billing (ready, awaiting approval)',
    is_active: false,
    schema_status: 'READY',
    study_state: 'READY',
    tables_documented: 47,
  }),
  // 9) Ready & approved.
  makeRow({
    id: 'demo-db-ready-approved',
    name: 'Billing (ready)',
    is_active: true,
    schema_status: 'READY',
    study_state: 'READY',
    tables_documented: 47,
  }),
  // 10) Ready partial — schema_status stays READY (a usable doc shipped);
  //     the partial signal lives on study_state.
  makeRow({
    id: 'demo-db-partial',
    name: 'Analytics (partial)',
    is_active: true,
    schema_status: 'READY',
    study_state: 'READY_PARTIAL',
    tables_documented: 30,
    tables_partial: 4,
  }),
  // 11) Stale — drift detected.
  makeRow({
    id: 'demo-db-stale',
    name: 'Inventory (drift)',
    is_active: true,
    schema_status: 'STALE',
    study_state: 'READY',
    tables_documented: 22,
  }),
  // 12) Failed — connection.
  makeRow({
    id: 'demo-db-failed',
    name: 'Legacy (connection failed)',
    is_active: false,
    schema_status: 'FAILED',
    study_state: 'CONNECT_FAILED',
    last_error_phase: 'CONNECT',
    last_error_message: 'Could not reach host on port 5432.',
  }),
  // 13) Failed mid-study.
  makeRow({
    id: 'demo-db-failed-describe',
    name: 'Legacy (describe failed)',
    is_active: true,
    schema_status: 'FAILED',
    study_state: 'DESCRIBING_FAILED',
    tables_documented: 14,
    last_error_phase: 'DESCRIBING',
    last_error_message: 'AI provider returned 429 — back off and retry.',
  }),
]
