/**
 * Skeleton shown by Next.js while a `/chat/[sessionId]` route segment is
 * preparing.  In practice this fires during client-side navigation between
 * sessions while the new RSC payload is being fetched — without it, the
 * router falls back to "stay on previous content until ready" which makes
 * the new chat feel slow to commit.
 *
 * Visuals match the message-thread shimmer in `MessageThread.tsx` so the
 * transition is seamless.  Keep this file dependency-free (no `'use client'`,
 * no hooks) so it can be served from cache.
 */
export default function ChatSessionLoading() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background md:h-screen">
      <div className="flex flex-1 flex-col gap-4 px-4 py-4" aria-busy="true">
        <div className="h-12 animate-pulse rounded-lg bg-muted/40" />
        <div className="ml-auto h-16 w-2/3 animate-pulse rounded-lg bg-muted/40" />
        <div className="h-20 w-3/4 animate-pulse rounded-lg bg-muted/40" />
        <div className="ml-auto h-12 w-1/2 animate-pulse rounded-lg bg-muted/40" />
      </div>
    </div>
  )
}
