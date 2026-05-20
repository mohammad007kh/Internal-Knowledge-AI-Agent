import { ChatLayout } from '@/components/chat/ChatLayout'

export const metadata = { title: 'Chat — Internal Knowledge AI' }

/**
 * Dynamic chat route: `/chat/[sessionId]`.
 *
 * The `sessionId` is awaited from URL params and threaded into
 * `<ChatLayout sessionId={...} />` as a prop so the server-rendered HTML
 * already commits to the message-thread branch on the very first paint.
 *
 * Pre-fix this page rendered `<ChatLayout />` with no prop and let the
 * client-side `SelectedSessionContext` derive the id from `useParams()`
 * after hydration.  But `useParams()` returns an empty object during the
 * SSR pass of a `'use client'` provider mounted via a server-component
 * page — so `sessionId` was `null` server-side, the `showEmptyHero`
 * branch rendered, and on hydration the page swapped to the real chat
 * surface.  The result was a ~100-300ms flash of the empty hero on every
 * hard refresh of `/chat/<id>`.
 *
 * NOTE on existence/404: validating that the session exists and the
 * caller has access to it would normally happen here via a server-side
 * fetch + `notFound()`, but server-component fetches need the user's
 * access token forwarded from cookies and the auth wiring isn't set up
 * for SSR yet.  Until that's in place, `MessageThread` handles the 404
 * client-side (renders a "Chat not found" state — see below).
 */
export default async function ChatSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>
}) {
  const { sessionId } = await params
  return <ChatLayout sessionId={sessionId} />
}
