/**
 * Chat API surface — request/response types and small fetch helpers.
 *
 * The persistent chat (`/sessions/{id}/messages`) lives in `useChatStream`
 * because it predates this module. This file holds the typed contract for
 * the *sandbox* endpoint added in Slice A: a one-off, admin-only chat that
 * never persists messages and is scoped to a single source.
 *
 * The wire grammar for the SSE stream is byte-identical to the persistent
 * chat (events: `delta`, `citations`, `clarification`, `guardrail_blocked`,
 * `done`, `error`, `title` — `title` is never emitted by sandbox but is
 * harmless if it ever is). That lets the same SSE consumer drain both.
 */
import { getToken } from '@/lib/token-store'

/**
 * Request body for `POST /api/v1/chat/sandbox/stream`.
 *
 * `history` is optional. The backend caps the conversation context at 20
 * turns server-side, but the UI also caps it client-side so we don't
 * waste bytes serializing turns the server will discard.
 */
export interface SandboxStreamRequest {
  source_id: string
  query: string
  history?: ReadonlyArray<{ role: 'user' | 'assistant'; content: string }>
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://localhost:8000'

/**
 * The number of past turns we'll send back to the server. The backend
 * enforces a max but we cap client-side too — keeps payloads bounded.
 */
export const SANDBOX_HISTORY_TURN_CAP = 20

/**
 * Open an SSE stream against the sandbox endpoint. Returns the raw `Response`
 * so the caller (the sandbox stream hook) can drain its `body` reader using
 * the same SSE-frame parser as `useChatStream`.
 *
 * Throws when the response is non-2xx; the caller should surface the message
 * via the existing error toast plumbing.
 */
export async function openSandboxStream(
  body: SandboxStreamRequest,
  signal: AbortSignal
): Promise<Response> {
  const token = getToken()
  const url = `${API_BASE}/api/v1/chat/sandbox/stream`

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      source_id: body.source_id,
      query: body.query.trim(),
      history: body.history?.slice(-SANDBOX_HISTORY_TURN_CAP) ?? [],
    } satisfies SandboxStreamRequest),
    credentials: 'include',
    signal,
  })

  if (!response.ok) {
    const fallback = `Sandbox stream failed with status ${response.status}`
    let errorText = fallback
    try {
      const contentType = response.headers.get('content-type') ?? ''
      if (
        contentType.includes('application/json') ||
        contentType.includes('application/problem+json')
      ) {
        const data = (await response.json()) as {
          detail?: unknown
          title?: unknown
          message?: unknown
        }
        const detail =
          typeof data.detail === 'string'
            ? data.detail
            : typeof data.title === 'string'
              ? data.title
              : typeof data.message === 'string'
                ? data.message
                : null
        if (detail) errorText = detail
      } else {
        const text = await response.text()
        if (text.trim()) errorText = text.trim().slice(0, 500)
      }
    } catch {
      errorText = fallback
    }
    throw new Error(errorText)
  }

  if (!response.body) {
    throw new Error('Sandbox stream response has no body')
  }

  return response
}
