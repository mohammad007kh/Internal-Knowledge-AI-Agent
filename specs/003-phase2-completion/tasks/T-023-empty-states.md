# T-023: Frontend — Empty States for All List Views

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As a user, when a list has no data, I want a clear message that explains why it's empty and what I can do next, rather than a blank or broken-looking page.
- **Requirement**: FR-041 (empty states on all list views)
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
| `ui_specs.dark_mode` | true |
| `conventions.files` | kebab-case (Next.js) |

### Domain Rules
- Reuse a single shared `<EmptyState>` component across all list views.
- Each call site provides: `icon`, `title`, `description`, and optionally a `action` (button/link).
- Empty state must be distinguishable from a loading skeleton (never show empty state while loading).
- Empty state shows ONLY when query has succeeded and `items.length === 0`.

### List Views That Need Empty States
| Page | Condition | Title | Description | Action |
|---|---|---|---|---|
| `/admin/sources` | No sources | "No sources yet" | "Add your first knowledge source to get started." | "Add Source" button → `/admin/sources/new` |
| `/admin/users` | No users | "No users yet" | "Invite your first team member." | "Invite User" button |
| `/admin/users` Invitations tab | No pending invitations | "No pending invitations" | "All invitations have been accepted or expired." | None |
| `/admin/policy` Guardrail events | No events | "No guardrail events" | "No messages have been flagged yet." | None |
| Chat sidebar session list | No sessions | "No conversations yet" | "Start a new chat to begin." | "New Chat" button |
| `/admin/sources/[id]` Sync tab | No sync history | "No sync history" | "This source hasn't been synced yet." | "Sync Now" button |

### Gate Criteria
- `<EmptyState>` component exists and is reusable.
- Each list above shows the correct empty state when data is absent.
- Empty state does not appear while data is loading (skeleton shows instead).
- Actions in empty states work (navigate to correct page or trigger mutation).

---

## 🎯 Objective

Create a shared `EmptyState` component and wire it into all six list views listed above.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/components/ui/EmptyState.tsx`** — Shared component:

```tsx
import { LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      <Icon className="h-12 w-12 text-muted-foreground" />
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-sm">{description}</p>
      {action && (
        action.href
          ? <Button asChild><a href={action.href}>{action.label}</a></Button>
          : <Button onClick={action.onClick}>{action.label}</Button>
      )}
    </div>
  );
}
```

### Files to Update (add EmptyState render)

For each list component below, wrap the table/list render with a conditional:

```tsx
// Pattern to apply in each list component:
{items.length === 0 ? (
  <EmptyState icon={DatabaseIcon} title="No sources yet" description="..." action={{...}} />
) : (
  <Table>...</Table>
)}
```

2. **`frontend/src/components/admin/SourcesTable.tsx`** — Add EmptyState when sources empty.
3. **`frontend/src/components/admin/UsersTable.tsx`** — Add EmptyState when users empty.
4. **`frontend/src/components/admin/InvitationsTable.tsx`** — Add EmptyState when invitations empty.
5. **`frontend/src/components/admin/GuardrailEventsTable.tsx`** — Add EmptyState when events empty.
6. **`frontend/src/components/layout/ChatSidebar.tsx`** — Add EmptyState when sessions empty.
7. **`frontend/src/components/admin/source-detail/SyncTab.tsx`** — Add EmptyState when no sync history.

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] `EmptyState` component created at `src/components/ui/EmptyState.tsx`.
- [ ] All 6 list views import and render `EmptyState` on empty data.
- [ ] `EmptyState` not shown during loading (check `isLoading` guard in each component).
- [ ] Action buttons in empty states are functional (navigate or trigger mutation).
- [ ] Dark mode classes applied (`text-muted-foreground` handles this via CSS variables).

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "EmptyState" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Clear all sources from DB → navigate to `/admin/sources` → empty state with "Add Source" button.
2. Click "Add Source" → navigates to source wizard.
3. Chat sidebar with no sessions → "No conversations yet" empty state with "New Chat" button.
4. Guardrail events with no data → clean empty state (no action button).

---

## 📝 Completion Log

- [ ] `EmptyState` component created.
- [ ] All 6 list views wired.
- [ ] No empty state shown during loading.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-041 → this task → commit SHA _TBD_.
