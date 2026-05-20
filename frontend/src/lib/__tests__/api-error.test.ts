/**
 * Unit tests for `extractApiErrorMessage` — the robust error-message extractor
 * shared by the source connection flows (Add-source wizard "Test connection",
 * source create, Edit-credentials dialog).
 *
 * The backend emits RFC-7807 `application/problem+json`. The actual message
 * can be at `response.data.detail` (flat — global problem handler) OR at
 * `response.data.detail.detail` (nested — FastAPI `HTTPException(detail={...})`).
 * The helper must handle BOTH, and must NEVER fall back to axios's useless
 * "Request failed with status code 422" when a `detail` is present.
 */
import { describe, expect, it } from 'vitest'

import { extractApiErrorMessage } from '../api-error'

/** Build an axios-like error (duck-typed — no axios import needed). */
function axiosLike(data: unknown, message = 'Request failed with status code 422') {
  return { isAxiosError: true, message, response: { status: 422, data } }
}

describe('extractApiErrorMessage', () => {
  it('returns the flat string `response.data.detail`', () => {
    const err = axiosLike({ type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail: 'Could not connect to database source' })
    expect(extractApiErrorMessage(err)).toBe('Could not connect to database source')
  })

  it('returns the nested `response.data.detail.detail` (HTTPException(detail={...}))', () => {
    const err = axiosLike({
      detail: { type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail: 'Could not connect' },
    })
    expect(extractApiErrorMessage(err)).toBe('Could not connect')
  })

  it('falls back to the inner `title` when the nested detail has no `detail`', () => {
    const err = axiosLike({ detail: { title: 'Bad Request', status: 400 } })
    expect(extractApiErrorMessage(err)).toBe('Bad Request')
  })

  it('falls back to the top-level `title` when there is no `detail`', () => {
    const err = axiosLike({ title: 'Bad Request', status: 400 })
    expect(extractApiErrorMessage(err)).toBe('Bad Request')
  })

  it('falls back to `response.data.message` when no detail/title present', () => {
    const err = axiosLike({ message: 'Validation failed' })
    expect(extractApiErrorMessage(err)).toBe('Validation failed')
  })

  it('returns `err.message` for a network error with no response body', () => {
    const err = { isAxiosError: true, message: 'Network Error', response: undefined }
    expect(extractApiErrorMessage(err)).toBe('Network Error')
  })

  it('returns `err.message` when the response body has no usable string fields', () => {
    const err = axiosLike({ status: 422 }, 'Request failed with status code 422')
    expect(extractApiErrorMessage(err)).toBe('Request failed with status code 422')
  })

  it('returns the message of a plain Error', () => {
    expect(extractApiErrorMessage(new Error('boom'))).toBe('boom')
  })

  it('returns the generic fallback for a string', () => {
    expect(extractApiErrorMessage('something broke')).toBe('An unexpected error occurred.')
  })

  it('returns the generic fallback for a number', () => {
    expect(extractApiErrorMessage(422)).toBe('An unexpected error occurred.')
  })

  it('returns the generic fallback for null', () => {
    expect(extractApiErrorMessage(null)).toBe('An unexpected error occurred.')
  })

  it('returns the generic fallback for undefined', () => {
    expect(extractApiErrorMessage(undefined)).toBe('An unexpected error occurred.')
  })

  it('never returns the generic axios message when a detail is present', () => {
    const err = axiosLike({ detail: 'Connection test failed with the supplied credentials. Credentials were NOT updated.' })
    const message = extractApiErrorMessage(err)
    expect(message).not.toMatch(/Request failed with status code/)
    expect(message).toBe('Connection test failed with the supplied credentials. Credentials were NOT updated.')
  })

  it('trims surrounding whitespace from the extracted detail', () => {
    const err = axiosLike({ detail: '  Could not connect  ' })
    expect(extractApiErrorMessage(err)).toBe('Could not connect')
  })

  it('ignores a non-string nested detail and uses the next available string', () => {
    const err = axiosLike({ detail: { detail: { nested: true }, title: 'Unprocessable Entity' } })
    expect(extractApiErrorMessage(err)).toBe('Unprocessable Entity')
  })

  it('surfaces the first msg from a FastAPI 422 validation-error array (with the field name)', () => {
    const err = axiosLike({
      detail: [
        { loc: ['body', 'host'], msg: 'field required', type: 'value_error.missing' },
        { loc: ['body', 'port'], msg: 'value is not a valid integer', type: 'type_error.integer' },
      ],
    })
    const message = extractApiErrorMessage(err)
    expect(message).toBe('host: field required')
    expect(message).not.toMatch(/Request failed with status code/)
  })

  it('falls back to the bare msg when a validation entry has no loc', () => {
    const err = axiosLike({ detail: [{ msg: 'invalid request', type: 'value_error' }] })
    expect(extractApiErrorMessage(err)).toBe('invalid request')
  })

  it('does not blow up on an empty detail array (falls through to title)', () => {
    const err = axiosLike({ detail: [], title: 'Unprocessable Entity' })
    expect(extractApiErrorMessage(err)).toBe('Unprocessable Entity')
  })
})
