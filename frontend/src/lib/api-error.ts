/**
 * api-error.ts — robust extraction of a human-readable message from an
 * arbitrary thrown value.
 *
 * The backend emits RFC-7807 `application/problem+json` bodies of the shape
 * `{ type, title, status, detail, instance, extra? }`. But FastAPI route
 * handlers that raise `HTTPException(detail={...})` nest the *whole* problem
 * dict under a top-level `detail` key — so the actual message can live at
 * `response.data.detail.detail` rather than `response.data.detail`. The global
 * problem-handler middleware, by contrast, returns it flat as
 * `response.data.detail` (a string). This helper handles BOTH layouts.
 *
 * The shared `apiClient` interceptor *does* flatten problem+json into a plain
 * `Error` in many cases — but only when the response content-type matches
 * `application/problem+json` exactly, and it drops the status code. Several
 * source-flow endpoints (`/sources/inspect`, `/sources/{id}/credentials`,
 * `/sources/{id}/test-connection`) call `apiClient` directly without that
 * normalisation, so the raw `AxiosError` reaches the caller and its `.message`
 * is the useless "Request failed with status code 422". This helper digs the
 * backend's `detail` out of `err.response.data` regardless.
 *
 * No `axios` import — the project's API layer is axios-based but we duck-type
 * the error shape so this helper stays dependency-free and works on any
 * axios-like error (including hand-built test fixtures).
 *
 * SECURITY: never returns `err.stack` or any nested object verbatim — only
 * trimmed strings the backend deliberately put on the wire.
 */

const GENERIC_FALLBACK = 'An unexpected error occurred.'

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Pull a message out of a problem+json-ish body. Accepts either:
 *   - `{ detail: "the message" }`                (flat — from the global handler)
 *   - `{ detail: { detail: "the message", title: "...", ... } }`  (nested — HTTPException(detail={...}))
 *   - `{ detail: [{ loc, msg, type }, ...] }`    (FastAPI default 422 — pydantic validation errors)
 *   - `{ title: "the title", ... }`              (no detail at all)
 *   - `{ message: "the message" }`               (non-RFC-7807 fallback shape)
 */
function messageFromBody(data: unknown): string | null {
  if (!isRecord(data)) return null

  const { detail } = data
  if (isNonEmptyString(detail)) return detail.trim()
  if (isRecord(detail)) {
    if (isNonEmptyString(detail.detail)) return detail.detail.trim()
    if (isNonEmptyString(detail.title)) return detail.title.trim()
  }
  // FastAPI's default 422 body is `{ detail: [{ loc, msg, type }, ...] }`.
  // Surface the first entry's `msg` (with the field name from `loc` when
  // present, e.g. "host: field required") rather than letting it fall
  // through to the useless "Request failed with status code 422".
  if (Array.isArray(detail) && detail.length > 0 && isRecord(detail[0])) {
    const first = detail[0]
    if (isNonEmptyString(first.msg)) {
      const loc = Array.isArray(first.loc) ? first.loc : []
      const field = loc.length > 0 ? loc[loc.length - 1] : undefined
      return isNonEmptyString(field)
        ? `${field.trim()}: ${first.msg.trim()}`
        : first.msg.trim()
    }
  }

  if (isNonEmptyString(data.title)) return data.title.trim()
  if (isNonEmptyString(data.message)) return data.message.trim()

  return null
}

/**
 * Extract the most useful human-readable message from an unknown thrown value.
 *
 * Resolution order:
 *   1. Axios-like error with a `response.data` body → the backend's `detail` /
 *      `detail.detail` / `detail.title` / `title` / `message` (whichever is a
 *      non-empty string).
 *   2. Axios-like error with no usable body → its `.message` (the network /
 *      timeout text, e.g. "Network Error").
 *   3. A plain `Error` → its `.message`.
 *   4. Anything else → the generic fallback.
 *
 * @example
 *   try { await inspectSourceApi(body) }
 *   catch (err) { toast.error(extractApiErrorMessage(err)) }
 */
export function extractApiErrorMessage(err: unknown): string {
  if (isRecord(err)) {
    // Axios-like: { response?: { data?: unknown }, message?: string, ... }
    if ('response' in err && isRecord(err.response)) {
      const bodyMessage = messageFromBody(err.response.data)
      if (bodyMessage !== null) return bodyMessage
    }
    if (isNonEmptyString((err as { message?: unknown }).message)) {
      return (err as { message: string }).message.trim()
    }
  }

  if (err instanceof Error && isNonEmptyString(err.message)) {
    return err.message.trim()
  }

  return GENERIC_FALLBACK
}
