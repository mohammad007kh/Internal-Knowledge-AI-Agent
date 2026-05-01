# T-017: Frontend — LLM Settings Admin Page

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to configure which LLM model and API key each pipeline stage uses, and verify the connection works, without SSH access to the server.
- **Requirement**: FR-021 (view LLM settings), FR-022 (edit per-stage config), FR-023 (save), FR-024 (test connection)
- **Priority**: P1

---

## 📋 Embedded Context

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | TanStack Query + React Context |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `conventions.files` | kebab-case (Next.js) |
| `api.versioning` | /api/v1/ |

### Domain Rules
- All API calls go through `apiClient` in `src/lib/api-client.ts`.
- TanStack Query for server state.
- API key full value is never returned by the backend; only `api_key_hint` (last 4 chars) is shown.
- The API key field must be a `type="password"` input; placeholder shows `••••{hint}`.
- Leaving the API key field blank on save must NOT overwrite the stored key (send `undefined`/omit field).
- "Test Connection" button calls `POST /admin/llm-settings/{stage}/test`; show latency + success/error.
- One card per pipeline stage; expandable or accordion style.

### Dependent Tasks
- T-009: Backend endpoints `GET/PUT /admin/llm-settings` and `POST /admin/llm-settings/{stage}/test`.

### Gate Criteria
- All pipeline stages listed (from API response).
- Each stage shows: label, description, provider, model, api_key_hint, temperature, max_tokens, enabled toggle.
- Saving without changing API key does NOT wipe the stored key.
- "Test Connection" shows latency in ms and success/error state.
- Provider change updates a "Model" dropdown with sensible model suggestions (static list per provider).

---

## 🎯 Objective

Build `/admin/llm-settings` page with per-stage configuration cards. Each card has a form (React Hook Form + Zod), a masked API key field, and a Test Connection button.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/app/(dashboard)/admin/llm-settings/page.tsx`** — Page:
   - `useQuery(['llm-settings'], getLLMSettings)`.
   - Renders a `<LLMStageCard>` for each stage.

2. **`frontend/src/components/admin/LLMStageCard.tsx`** — Per-stage card:

   Form fields:
   - Provider: `<Select>` options: `openai`, `anthropic`, `azure_openai`, `ollama`, `custom`.
   - Model: `<Select>` seeded from a `PROVIDER_MODELS` map (static); user can also type freely.
   - API Key: `<Input type="password">` placeholder `"••••{api_key_hint}"`. Empty value on submit = omit from PATCH body.
   - Base URL: `<Input>` (shown only when provider = `custom` or `azure_openai`).
   - Temperature: `<Input type="number" step="0.1" min="0" max="2">`.
   - Max Tokens: `<Input type="number" step="1" min="1" max="32768">`.
   - Enabled: `<Switch>`.
   - Save button → `PUT /admin/llm-settings/{stage}`.
   - Test Connection button → `POST /admin/llm-settings/{stage}/test` → show inline result.

   Test result inline display:
   ```tsx
   {testResult && (
     <p className={testResult.success ? 'text-green-600' : 'text-red-600'}>
       {testResult.success
         ? `Connected (${testResult.latency_ms}ms)`
         : `Failed: ${testResult.message}`}
     </p>
   )}
   ```

3. **`frontend/src/lib/api/llm-settings.ts`** — API functions:
   ```ts
   export const getLLMSettings = () => apiClient.get<LLMSettingsResponse>('/admin/llm-settings');
   export const updateLLMStage = (stage: string, body: LLMStageUpdateRequest) =>
     apiClient.put<LLMStageConfig>(`/admin/llm-settings/${stage}`, body);
   export const testLLMStage = (stage: string) =>
     apiClient.post<LLMTestResult>(`/admin/llm-settings/${stage}/test`);
   ```

4. **`frontend/src/types/llm-settings.ts`** — Types:
   ```ts
   export interface LLMStageConfig {
     stage: string;
     label: string;
     description: string;
     provider: string;
     model: string;
     api_key_hint: string;
     base_url: string | null;
     temperature: number;
     max_tokens: number;
     enabled: boolean;
   }
   export interface LLMStageUpdateRequest {
     provider: string;
     model: string;
     api_key?: string;
     base_url?: string | null;
     temperature: number;
     max_tokens: number;
     enabled: boolean;
   }
   export interface LLMTestResult {
     success: boolean;
     latency_ms?: number;
     message: string;
   }
   ```

### Zod Schema (per card)
```ts
const llmStageSchema = z.object({
  provider: z.string().min(1),
  model: z.string().min(1),
  api_key: z.string().optional(),
  base_url: z.string().url().optional().or(z.literal('')),
  temperature: z.number().min(0).max(2),
  max_tokens: z.number().int().min(1).max(32768),
  enabled: z.boolean(),
});
```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] Page at `app/(dashboard)/admin/llm-settings/page.tsx`.
- [ ] Navigation link added (handled in T-020 — just ensure the page exists).
- [ ] `LLMStageCard` form uses React Hook Form + Zod resolver.
- [ ] API key field masked; empty on submit means "no change".
- [ ] Test Connection shows inline success/error with latency.
- [ ] `getLLMSettings`, `updateLLMStage`, `testLLMStage` in `src/lib/api/llm-settings.ts`.
- [ ] Dark mode classes applied to all cards.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "llm-settings\|LLMStage" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Navigate to `/admin/llm-settings` → all pipeline stages visible as cards.
2. Change provider on a card → model dropdown updates.
3. Leave API key blank → save → key unchanged on next page load.
4. Click "Test Connection" → inline result shows latency or error message.
5. Toggle `enabled` to false → save → stage shows as disabled.

---

## 📝 Completion Log

- [ ] Page and `LLMStageCard` component implemented.
- [ ] Form validation with Zod.
- [ ] API key masking and omit-if-empty behavior.
- [ ] Test Connection inline result.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-021, FR-022, FR-023, FR-024 → this task → commit SHA _TBD_.
