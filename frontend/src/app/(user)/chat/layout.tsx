/**
 * The selected-session provider now wraps the entire user shell (see
 * `UserSidebar`) so the sidebar's inline chat history can read and update the
 * active session from anywhere in the app. The chat route therefore no
 * longer needs its own provider — the shell layout is sufficient.
 */
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
