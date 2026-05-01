# T-025: Frontend — Network Offline Toast Notification

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As a user, when my internet connection drops while using the app, I want an immediate notification so I know why the app stopped responding — and a confirmation when I'm back online.
- **Requirement**: FR-043 (network offline/online toast notification)
- **Priority**: P2

---

## 📋 Embedded Context

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `ui_specs.notifications` | sonner |
| `ui_specs.icons` | lucide-react |
| `ui_specs.dark_mode` | true |
| `conventions.files` | kebab-case (Next.js) |

### Domain Rules
- Use the browser's `navigator.onLine` + `window.addEventListener('offline'/'online')` events.
- Toast library is `sonner` (already installed).
- Offline toast: persistent (not auto-dismissed) with `WifiOff` icon.
- Online toast: auto-dismissed after 3 seconds with `Wifi` icon.
- Logic must live in a single hook `useNetworkStatus` so it can be used in tests.
- The hook must clean up event listeners on unmount.
- Only one offline toast at a time — if user toggles offline/online rapidly, do not stack toasts.

### Gate Criteria
- Going offline → persistent toast "You are offline. Check your connection."
- Coming back online → the offline toast is dismissed; new toast "You're back online." (auto-dismiss 3s).
- No duplicate toasts if offline event fires multiple times.
- Hook cleans up listeners on unmount.

---

## 🎯 Objective

Add a `useNetworkStatus` hook that listens to browser online/offline events and shows appropriate sonner toasts. Mount the hook in the root layout so it's active app-wide.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/hooks/use-network-status.ts`** — Hook:

```ts
'use client';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

const OFFLINE_TOAST_ID = 'network-offline';

export function useNetworkStatus() {
  const offlineToastShown = useRef(false);

  useEffect(() => {
    function handleOffline() {
      if (offlineToastShown.current) return;
      offlineToastShown.current = true;
      toast.error('You are offline. Check your connection.', {
        id: OFFLINE_TOAST_ID,
        duration: Infinity,
        icon: '📡',
      });
    }

    function handleOnline() {
      if (!offlineToastShown.current) return;
      toast.dismiss(OFFLINE_TOAST_ID);
      offlineToastShown.current = false;
      toast.success("You're back online.", { duration: 3000, icon: '✅' });
    }

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    // Handle case where app loads while already offline
    if (!navigator.onLine) handleOffline();

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);
}
```

### Files to Update

2. **`frontend/src/app/(dashboard)/layout.tsx`** — Mount hook:

```tsx
'use client';
import { useNetworkStatus } from '@/hooks/use-network-status';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useNetworkStatus();
  return <>{children}</>;
}
```

Note: if the layout is already a Server Component, extract the hook mount into a small client wrapper component:
```tsx
// frontend/src/components/layout/NetworkStatusProvider.tsx
'use client';
export function NetworkStatusProvider() {
  useNetworkStatus();
  return null;
}
// Then include <NetworkStatusProvider /> in the layout JSX
```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] `useNetworkStatus` hook created at `src/hooks/use-network-status.ts`.
- [ ] Hook mounted in `(dashboard)/layout.tsx` (directly or via `NetworkStatusProvider`).
- [ ] Offline toast uses `id: 'network-offline'` to prevent duplicates.
- [ ] Online toast dismisses the offline toast before showing success.
- [ ] App-loads-offline case handled (check `navigator.onLine` on mount).
- [ ] Event listeners cleaned up on unmount.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "use-network-status\|NetworkStatus" | head -10
```
Expected: no TypeScript errors.

Manual smoke test (Chrome DevTools → Network tab → Offline):
1. Load app → go offline via DevTools → toast appears: "You are offline. Check your connection."
2. Toggle DevTools back to online → offline toast dismissed; "You're back online." toast appears and auto-dismisses.
3. Go offline/online rapidly 3× → no duplicate toasts stacked.

---

## 📝 Completion Log

- [ ] `useNetworkStatus` hook implemented.
- [ ] Hook mounted in dashboard layout.
- [ ] Offline toast is persistent; online toast auto-dismisses.
- [ ] No duplicate toasts.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-043 → this task → commit SHA _TBD_.
