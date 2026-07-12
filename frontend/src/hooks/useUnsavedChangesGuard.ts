'use client'

import { useEffect } from 'react'

/**
 * useUnsavedChangesGuard
 * ----------------------
 * Two-layer "leave anyway?" guard for any form with an `isDirty` signal.
 *
 *  1. **`beforeunload` listener** — fires when the user closes the tab,
 *     refreshes, types a new URL into the address bar, or navigates away
 *     from the SPA via browser back/forward. The browser shows its own
 *     native confirm dialog (the `message` argument is ignored by modern
 *     Chromium/Firefox/Safari but kept for legacy callers).
 *
 *  2. **Capture-phase document `click` interceptor** — Next.js App Router
 *     exposes no official route-change blocker. Rather than monkey-patch
 *     `history.pushState` or wrap `useRouter`, we intercept clicks at the
 *     document level *before* `<Link>` / `<a>` handlers run. If the click
 *     resolves to a same-origin URL different from the current one, we
 *     fire `window.confirm(message)` and cancel the click on decline.
 *
 * The listeners are wired only while `isDirty === true` and torn down on
 * unmount or when `isDirty` flips back to false. That prevents the
 * dreaded zombie listener leak where a saved-then-edited form would
 * accumulate handlers across remounts.
 *
 * Modifier-clicks (cmd/ctrl/shift/alt), middle-click, `target="_blank"`,
 * and `download` anchors are intentionally NOT intercepted — they don't
 * unload the current view.
 *
 * ## Known limitation — programmatic navigation is NOT guarded
 *
 * This hook only intercepts (1) browser unload and (2) real DOM <a>/<Link>
 * clicks. Imperative App-Router navigation — `router.push()`,
 * `router.replace()`, `router.back()`, or `redirect()` — bypasses both
 * layers entirely and will navigate away WITHOUT a confirm prompt. Next.js
 * App Router exposes no official route-change blocker, so callers that
 * navigate programmatically while a form is dirty must run their own
 * `window.confirm` before the call (FX41).
 *
 * @example
 *   const isDirty = form.formState.isDirty
 *   useUnsavedChangesGuard(isDirty)
 */
const DEFAULT_MESSAGE = 'You have unsaved changes. Leave anyway?'

export function useUnsavedChangesGuard(
  isDirty: boolean,
  message: string = DEFAULT_MESSAGE
): void {
  useEffect(() => {
    if (!isDirty) {
      return
    }

    // Layer 1: browser-level unload (tab close, refresh, address-bar nav).
    function onBeforeUnload(event: BeforeUnloadEvent): void {
      event.preventDefault()
      // Setting returnValue is the legacy contract still required by Chrome
      // and some Safari builds to actually surface the native dialog.
      event.returnValue = message
    }

    // Layer 2: in-app anchor / Link clicks (sidebar, breadcrumbs, etc.).
    // Capture phase so we intercept BEFORE Next's Link handler navigates.
    function onDocumentClick(event: MouseEvent): void {
      // Respect the user explicitly opening in a new tab / window.
      if (event.defaultPrevented) return
      if (event.button !== 0) return
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return

      const target = event.target
      if (!(target instanceof Element)) return

      const anchor = target.closest('a')
      if (!anchor) return

      // Anchors with no href, target=_blank, or download don't replace the
      // current document — let them through.
      const href = anchor.getAttribute('href')
      if (!href) return
      if (anchor.target && anchor.target !== '' && anchor.target !== '_self') return
      if (anchor.hasAttribute('download')) return

      let destination: URL
      try {
        destination = new URL(anchor.href, window.location.href)
      } catch {
        return
      }

      // Different origin → browser will issue beforeunload anyway; don't
      // double-prompt.
      if (destination.origin !== window.location.origin) return

      // In-page hash / same URL → no real navigation, no prompt.
      const sameUrl =
        destination.pathname === window.location.pathname &&
        destination.search === window.location.search
      if (sameUrl) return

      const confirmed = window.confirm(message)
      if (!confirmed) {
        event.preventDefault()
        event.stopPropagation()
      }
    }

    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onDocumentClick, true)

    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onDocumentClick, true)
    }
  }, [isDirty, message])
}
