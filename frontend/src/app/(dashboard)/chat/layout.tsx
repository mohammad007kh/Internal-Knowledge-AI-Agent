import { SelectedSessionProvider } from '@/components/chat/SelectedSessionContext'

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <SelectedSessionProvider>{children}</SelectedSessionProvider>
}
