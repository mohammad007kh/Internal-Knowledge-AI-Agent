/**
 * Route-segment loading slot for `/chat/[sessionId]`.
 *
 * Returns `null` (not a skeleton) on purpose — when the user clicks
 * between sessions or the auto-create-on-send flow lands a new session
 * id, the previous chat tree stays mounted via `startTransition` and
 * React paints a route-stable surface.  Showing a skeleton during that
 * transition would replace the in-flight optimistic user bubble with a
 * shimmer for ~80–200ms, which is exactly the "vanishing message" bug
 * we just fixed (UX P1-A).  MessageThread already has its own internal
 * shimmer (`isLoading && !persisted.length` branch) for the slower
 * "session id is set, messages query is fetching" case — that path
 * remains intact.
 *
 * Kept as a file (vs. deleted) to satisfy Next.js's loading-segment
 * convention and as a documented hook point if a future page-level
 * server fetch is added.
 */
export default function ChatSessionLoading() {
  return null
}
