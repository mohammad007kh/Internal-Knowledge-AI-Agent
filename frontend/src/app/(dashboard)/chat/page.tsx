import { ChatLayout } from '@/components/chat/ChatLayout'
import { SelectedSessionProvider } from '@/components/chat/SelectedSessionContext'

export const metadata = { title: 'Chat — Internal Knowledge AI' }

export default function ChatPage() {
  return (
    <SelectedSessionProvider>
      <ChatLayout />
    </SelectedSessionProvider>
  )
}
