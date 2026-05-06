import { ChatLayout } from '@/components/chat/ChatLayout'

export const metadata = { title: 'Chat — Internal Knowledge AI' }

/**
 * Dynamic chat route: `/chat/[sessionId]`.
 *
 * This server component is intentionally minimal — it only renders
 * `<ChatLayout />`. The active session id is read from the URL via
 * `useParams()` inside `SelectedSessionContext` (the provider lives in the
 * user shell), so this page does not need to thread `sessionId` through
 * props. Refreshing the page therefore preserves the active chat.
 *
 * In Next.js 15 dynamic route params are async. We `await` them to satisfy
 * the type contract even though we do not use the value here — keeping this
 * shape makes future server-side validation (e.g. 404 on missing session)
 * trivial to add.
 */
export default async function ChatSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>
}) {
  await params
  return <ChatLayout />
}
