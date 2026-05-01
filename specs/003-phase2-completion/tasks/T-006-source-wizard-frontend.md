# T-006: Source Registration Wizard (5-Step Frontend)

**Status**: Not Started
**Created**: 2026-04-21
**User Story**: US-1
**Requirement**: FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008
**Priority**: P0
**Feature**: Phase 2 — Product Completion (Internal Knowledge AI Agent)
**Branch**: `003-phase2-completion`
**Platform**: Web (Next.js 15 App Router frontend)

---

## 📋 Embedded Context

### Feature Summary
Phase 2 closes the gap between the current working skeleton and the full product vision. This task replaces the existing raw JSON source-creation form with a multi-step guided wizard that walks administrators through selecting a source type, entering connection details, reviewing an AI-generated description, configuring sync/retrieval behavior, and confirming the source creation. The wizard is the primary onboarding surface for new data sources and must support relational databases, NoSQL stores, uploaded files, web URLs, and SaaS integrations.

### Registry Standards (Project Defaults — Locked)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | context + TanStack Query |
| `frontend.data_fetching` | tanstack-query |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `frontend.routing` | next-router (App Router) |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `ui_specs.responsive` | true |
| `ui_specs.accessibility` | wcag-aa |
| `conventions.files` | kebab-case (Next.js components) |
| `conventions.classes` | PascalCase |
| `backend.sse_pattern` | fetch() + ReadableStream (NOT EventSource) |
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer (Authorization: Bearer <token>) |

### Domain Rules (frontend-developer + typescript-pro)
- All API calls go through `apiClient` in `src/lib/api-client.ts` — never use raw `fetch` or axios directly in components
- **Exception**: Direct PUT to MinIO presigned URLs MUST use vanilla `fetch()` — the URL is external and already signed
- Define typed API functions in `src/lib/api/` directory
- TanStack Query for ALL server state — never store server data in `useState`
- Use `useQuery` and `useMutation` for all API interactions
- Forms use React Hook Form + Zod schema validation
- All new pages use shadcn/ui components
- Accessibility: all interactive elements need proper `aria-label` or visible label
- File naming: kebab-case for files, PascalCase for React components

### API Contracts
```
POST /api/v1/sources/inspect
  Body: { source_type: string, connection: object }
  Response: { description: string, schema_summary: object }

POST /api/v1/sources/upload-url
  Body: { filename: string, content_type: string }
  Response: { upload_url: string, object_key: string }

POST /api/v1/sources
  Body: { name, source_type, connection?, object_key?, description, sync_mode, sync_schedule?, retrieval_mode, citations_enabled }
  Response 201: Source object
```

### Gate Criteria
- TypeScript strict mode compiles without new errors
- All 5 wizard steps render without runtime errors
- Source type grid displays all 11 supported source types
- Connection forms validate required fields before advancing
- File uploads PUT directly to presigned URLs (not through API server)
- AI description step handles inspect failure gracefully
- On successful create: redirect to detail page with `toast.success`
- WCAG AA: form labels associated with inputs, errors announced via `aria-live`

---

## 🎯 Objective

Build a 5-step guided wizard that replaces the current raw JSON form at `/admin/sources/new`. Administrators must be able to register any supported source type without writing JSON by hand. The wizard coordinates calls to `sources/inspect`, `sources/upload-url`, and `sources` create endpoints, producing a typed `Source` record that triggers an initial sync on the backend.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/components/admin/SourceWizard/index.tsx`** — Main orchestrator
   - Holds wizard state: `currentStep`, `sourceType`, `connection`, `files[]`, `description`, `syncMode`, `syncSchedule`, `retrievalMode`, `citationsEnabled`
   - Renders a horizontal stepper showing 5 steps (use shadcn-style pill layout)
   - Renders the active step component
   - Previous / Next navigation (disabled appropriately)
   - Uses `useMutation` for `createSource`
   - Signature: `export function SourceWizard(): JSX.Element`

2. **`frontend/src/components/admin/SourceWizard/StepSourceType.tsx`** — Step 1
   - Grid of source type cards (responsive: 2 cols mobile, 3 tablet, 4 desktop)
   - Source types grouped visually by category:
     - Relational DB: `postgresql`, `mysql`, `mssql` — icon `Database`
     - NoSQL: `mongodb` — icon `Database`
     - Documents: `pdf`, `docx`, `xlsx`, `csv`, `txt`, `markdown` — icon `FileText`
     - Web: `web_url` — icon `Globe`
     - Integrations: `confluence`, `sharepoint` — icon `Plug`
   - Each card: icon, display name, one-line description
   - Click → set `sourceType` and advance to Step 2
   - Props: `{ onSelect: (type: SourceType) => void }`

3. **`frontend/src/components/admin/SourceWizard/StepConnectionForm.tsx`** — Step 2
   - Renders type-appropriate form using React Hook Form + Zod
   - Zod schemas defined per source type (switch-case or map keyed by `sourceType`)
   - **Relational DB (`postgresql`/`mysql`/`mssql`)**: Source Name, Host, Port (default 5432/3306/1433), Database Name, Username, Password, SSL Mode (`disable` | `prefer` | `require`)
   - **MongoDB**: Source Name, Connection URI, Database Name, Collection(s) (comma-separated or tag input)
   - **File types** (`pdf`/`docx`/`xlsx`/`csv`/`txt`/`markdown`): Source Name + drag-and-drop zone using native HTML5 drag events; accept multiple; max 50MB each; show per-file progress bar. Flow:
     1. On drop: call `getUploadUrl(filename, contentType)` via `apiClient`
     2. PUT file directly to `upload_url` with vanilla `fetch()` and `XMLHttpRequest`-style progress (use `fetch` + manual chunk if progress required; otherwise show indeterminate spinner then checkmark)
     3. Store returned `object_key` into form state
   - **Web URL**: Source Name, URL (must be valid https), Crawl Depth (0–3, integer input)
   - **Confluence**: Source Name, Base URL, Space Key, API Token
   - **SharePoint**: Source Name, Site URL, Client ID, Client Secret, Tenant ID
   - "Test Connection" button (DB + NoSQL + integrations only): calls `inspectSource(sourceType, connection)` inline and shows success/failure inline without leaving the step
   - Next button disabled until form is valid
   - Props: `{ sourceType: SourceType, onNext: (connection: object, files?: UploadedFile[]) => void, onBack: () => void }`

4. **`frontend/src/components/admin/SourceWizard/StepAIDescription.tsx`** — Step 3
   - On mount: triggers `useMutation` for `inspectSource` (unless already called in Step 2)
   - Loading state: "Inspecting source schema..." with shadcn Skeleton + spinner
   - Display result in editable shadcn `<Textarea>` (min 5 rows)
   - Placeholder if inspect fails: "Describe this source..." (user must type something)
   - "Approve Description" button advances to Step 4 (disabled while empty)
   - Props: `{ sourceType, connection, initialDescription?: string, onNext: (description: string) => void, onBack: () => void }`

5. **`frontend/src/components/admin/SourceWizard/StepConfiguration.tsx`** — Step 4
   - **Sync Mode** (shadcn RadioGroup): `manual` | `scheduled` | `delta`
     - If `scheduled`: show cron expression input + plain-language preview below
     - Use `cronstrue` library if available; otherwise simple preset dropdown + advanced input
   - **Retrieval Mode** (DB sources only — hide for files/web): radio `vector_only` | `text_to_query` | `hybrid`
   - **Citations Enabled** (shadcn Switch, default ON)
   - Props: `{ sourceType, onNext: (config: ConfigData) => void, onBack: () => void }`

6. **`frontend/src/components/admin/SourceWizard/StepReview.tsx`** — Step 5
   - Summary card grouping all collected values:
     - Identity: name, type
     - Connection: masked secrets (show `••••••••` for passwords/tokens)
     - Description: truncated preview with "view full" expander
     - Configuration: sync mode, schedule, retrieval mode, citations
   - "Create Source" button calls `createSource` mutation
   - On success: `router.push('/admin/sources/[id]')` + `toast.success("Source created")`
   - On error: inline `<Alert variant="destructive">` with message
   - Props: `{ data: FullWizardData, onBack: () => void }`

7. **`frontend/src/lib/api/sources.ts`** — Typed API functions
   ```typescript
   import { apiClient } from '@/lib/api-client'

   export type SourceType =
     | 'postgresql' | 'mysql' | 'mssql'
     | 'mongodb'
     | 'pdf' | 'docx' | 'xlsx' | 'csv' | 'txt' | 'markdown'
     | 'web_url'
     | 'confluence' | 'sharepoint'

   export type SyncMode = 'manual' | 'scheduled' | 'delta'
   export type RetrievalMode = 'vector_only' | 'text_to_query' | 'hybrid'

   export interface InspectResult {
     description: string
     schema_summary: Record<string, unknown>
   }

   export interface UploadUrlResult {
     upload_url: string
     object_key: string
   }

   export interface Source {
     id: string
     name: string
     source_type: SourceType
     description: string
     sync_mode: SyncMode
     retrieval_mode: RetrievalMode
     citations_enabled: boolean
     created_at: string
     updated_at: string
   }

   export interface SourceCreateInput {
     name: string
     source_type: SourceType
     connection?: Record<string, unknown>
     object_key?: string
     description: string
     sync_mode: SyncMode
     sync_schedule?: string
     retrieval_mode: RetrievalMode
     citations_enabled: boolean
   }

   export async function inspectSource(
     source_type: SourceType,
     connection: Record<string, unknown>
   ): Promise<InspectResult> {
     return apiClient.post('/api/v1/sources/inspect', { source_type, connection })
   }

   export async function getUploadUrl(
     filename: string,
     content_type: string
   ): Promise<UploadUrlResult> {
     return apiClient.post('/api/v1/sources/upload-url', { filename, content_type })
   }

   export async function createSource(data: SourceCreateInput): Promise<Source> {
     return apiClient.post('/api/v1/sources', data)
   }

   // Helper for direct presigned PUT — uses vanilla fetch, NOT apiClient
   export async function uploadToPresignedUrl(
     url: string,
     file: File,
     onProgress?: (pct: number) => void
   ): Promise<void> {
     const response = await fetch(url, {
       method: 'PUT',
       body: file,
       headers: { 'Content-Type': file.type }
     })
     if (!response.ok) throw new Error(`Upload failed: ${response.status}`)
     onProgress?.(100)
   }
   ```

### Files to Update

- **`frontend/src/app/(dashboard)/admin/sources/new/page.tsx`**
  - Replace existing raw JSON form content with:
    ```tsx
    import { SourceWizard } from '@/components/admin/SourceWizard'

    export default function NewSourcePage() {
      return (
        <div className="container mx-auto py-8 max-w-4xl">
          <h1 className="text-2xl font-bold mb-6">Register New Source</h1>
          <SourceWizard />
        </div>
      )
    }
    ```

### Code / Logic Requirements

- **State machine**: use a discriminated union for wizard state to prevent invalid transitions
- **Zod schemas**: define one schema per source type; resolve at form init based on `sourceType`
- **Stepper component**: indicate current, completed (with check icon), and upcoming steps
- **Validation**: each step's Next button disabled until step form is valid
- **Immutability**: wizard state updates always produce a new state object (`{ ...prev, field: value }`) — never mutate
- **Error handling**: all mutations surface errors via `sonner` toast (`toast.error`) + inline alert; `inspect` failure in Step 3 degrades gracefully to empty description
- **File size**: keep `index.tsx` orchestrator under 300 lines; each step file under 250 lines

---

## 🔌 Wiring Checklist (Web)

- [ ] `SourceWizard/index.tsx` imports all 5 step components
- [ ] `SourceWizard/index.tsx` imports `createSource` from `@/lib/api/sources`
- [ ] `StepConnectionForm.tsx` imports `inspectSource`, `getUploadUrl`, `uploadToPresignedUrl`
- [ ] `StepAIDescription.tsx` imports `inspectSource`
- [ ] `app/(dashboard)/admin/sources/new/page.tsx` renders `<SourceWizard />`
- [ ] `sources.ts` uses `apiClient` for all calls (except `uploadToPresignedUrl` which uses vanilla `fetch`)
- [ ] All mutations wrapped in `useMutation` from TanStack Query
- [ ] On successful create: `queryClient.invalidateQueries({ queryKey: ['sources'] })` called
- [ ] Toast notifications use `sonner`'s `toast` function
- [ ] All form inputs use shadcn primitives (Input, Textarea, Select, RadioGroup, Switch)

---

## ✅ Verification

### Verification Command
```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```
**Expected**: No TypeScript errors (or only pre-existing errors unrelated to SourceWizard files).

### Manual Verification
1. Navigate to `/admin/sources/new`
2. Confirm wizard stepper renders (5 steps visible)
3. Click a PostgreSQL card → connection form renders with host/port/db/user/pass fields
4. Fill invalid port → Next button stays disabled
5. Click "Test Connection" with good creds → inline success badge
6. Upload a PDF (from a file source type) → progress indicator → object_key captured
7. Step 3 shows AI description, editable
8. Step 4 shows sync/retrieval/citations controls (retrieval hidden for file types)
9. Step 5 shows summary with masked passwords
10. Click "Create Source" → redirected to `/admin/sources/[id]` with success toast

### Accessibility Checklist
- [ ] All form inputs have `<label>` with matching `htmlFor`
- [ ] Step headings use `<h2>` semantic tags
- [ ] Stepper exposes `aria-current="step"` on active step
- [ ] Error messages use `role="alert"` or `aria-live="polite"`
- [ ] Drag-drop zone keyboard-accessible (Enter/Space triggers file picker)
- [ ] Password fields have `type="password"` and reveal toggle has `aria-label`

---

## 📝 Completion Log

<!-- To be filled during /atomicspec.implement -->

- **Started**:
- **Completed**:
- **Files Changed**:
- **Verification Output**:
- **Notes**:
