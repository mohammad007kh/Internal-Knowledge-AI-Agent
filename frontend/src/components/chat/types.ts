export interface Citation {
  id: string
  document_id: string
  source_id: string
  source_name: string
  document_title: string
  excerpt: string
  score: number
  url?: string | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  citations?: Citation[]
}

export interface SessionMessagesResponse {
  session: { id: string; title: string; source_ids: string[] }
  messages: Message[]
}
