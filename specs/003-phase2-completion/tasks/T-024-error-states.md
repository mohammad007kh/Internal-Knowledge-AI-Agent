# T-024: Frontend — Error States + Retry for All Data-Loading Pages

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As a user, when a page fails to load data, I want a clear error message with a Retry button so I can recover without refreshing the entire browser tab.
- **Requirement**: FR-042 (error states with retry on all data-loading pages)
- **Priority**: P2

---

## 📋 Embedded Context

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `conventions.files` | kebab-case (Next.js) |

### Domain Rules
- Reuse a single shared `<ErrorState>` component.
- TanStack Query's `isError` + `refetch` provide the error detection and retry mechanism.
- Do NOT show a full-page error for non-critical secondary queries (e.g., stats sidebar). Use inline inline error text instead.
- Error message shown to user must NOT include raw API error details or stack traces.
- 401 errors should redirect to login (already handled by `apiClient` interceptor — do not duplicate here).
- 403 errors → "You don't have permission to view this page."
- 404 errors → "This page doesn't exist."
- All other errors → generic "Something went wrong. Please try again."

### Pages That Need Error States
All pages that load data via `useQuery`:
- `/admin/sources` (sources list)
- `/admin/sources/[id]` (source detail)
- `/admin/users` (users + invitations)
- `/admin/llm-settings`
- `/admin/policy` (policy + guardrail events)
- `/admin/analytics` (existing)
- `/chat/[id]` (messages)
- `/profile`

### Gate Criteria
- `<ErrorState>` component exists with Retry button.
- All pages listed above show `ErrorState` when query fails.
- Retry button calls `refetch()` from TanStack Query.
- Error state does not show during loading (skeleton shows instead).
- 403 shows permission message; 404 shows not-found message; others show generic message.

---

## 🎯 Objective

Create a shared `ErrorState` component and add error handling to every data-loading page. Retry calls TanStack Query's `refetch()` — no full page reload.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/components/ui/ErrorState.tsx`** — Shared component:

```tsx
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({
  message = 'Something went wrong. Please try again.',
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      <AlertCircle className="h-12 w-12 text-destructive" />
      <h3 className="text-lg font-semibold text-destructive">Error</h3>
      <p className="text-sm text-muted-foreground max-w-sm">{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
```

2. **`frontend/src/lib/errors.ts`** — Error message resolver:

```ts
export function getErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'status' in error) {
    const status = (error as { status: number }).status;
    if (status === 403) return "You don't have permission to view this page.";
    if (status === 404) return "This page doesn't exist.";
  }
  return 'Something went wrong. Please try again.';
}
```

### Files to Update (add error handling pattern)

In each data-loading page, apply this pattern:

```tsx
const { data, isLoading, isError, error, refetch } = useQuery([...]);

if (isLoading) return <PageSkeleton />;
if (isError) return (
  <ErrorState
    message={getErrorMessage(error)}
    onRetry={() => refetch()}
  />
);
```

Apply to all pages listed in the gate criteria above.

### Loading Skeletons (if not already present)
Each page should already have a skeleton — if missing, use shadcn `Skeleton` component:
```tsx
function PageSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}
```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] `ErrorState` component created at `src/components/ui/ErrorState.tsx`.
- [ ] `getErrorMessage` helper in `src/lib/errors.ts`.
- [ ] All 8 pages listed use `isError` → `<ErrorState onRetry={refetch}>` pattern.
- [ ] `isLoading` guard ensures skeleton shown before error state.
- [ ] 401 errors NOT handled here (handled by apiClient interceptor).
- [ ] Dark mode classes applied.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "ErrorState\|errors" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Disconnect backend → navigate to `/admin/sources` → ErrorState shows with "Try again" button.
2. Click "Try again" → retries without page reload; if backend is back, data loads.
3. Navigate to a source that doesn't exist (`/admin/sources/nonexistent-id`) → 404 error message shown.

---

## 📝 Completion Log

- [ ] `ErrorState` component created.
- [ ] `getErrorMessage` helper implemented.
- [ ] All 8 pages wired with error handling.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-042 → this task → commit SHA _TBD_.
