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

export interface MessageFeedback {
  id: string
  rating: 1 | -1
  comment: string | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  citations?: Citation[]
  feedback?: MessageFeedback | null
}

export interface SessionMessagesResponse {
  // `title` is nullable since U15 (lazy creation): a freshly-created session
  // may not have a title yet — the sidebar falls back to a preview of the
  // first user message in that window.
  session: { id: string; title: string | null; source_ids: string[] }
  messages: Message[]
}
