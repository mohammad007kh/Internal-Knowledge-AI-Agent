/**
 * F9 — AI-naming opt-in checkbox tests.
 *
 * The form is large; this suite focuses on the contract that the checkbox
 * sits at the bottom of:
 *
 *   1. Default state: unchecked, name + description editable, submit blocks
 *      on empty name.
 *   2. Checked: fields disabled, name validation relaxes, submit payload
 *      includes `auto_name_and_description: true` with empty `name` /
 *      `description`.
 *   3. Re-unchecked: fields re-enable and validation re-tightens.
 */

import type { CreatedSource, CreateSourcePayload } from '@/hooks/use-create-source'
import type { UploadFileResult } from '@/hooks/use-upload-url'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks — registered BEFORE the page is imported
// ---------------------------------------------------------------------------

const createSourceMock = vi.fn(
  async (payload: CreateSourcePayload): Promise<CreatedSource> => ({
    id: 'src-new',
    name: payload.name || 'AI placeholder',
    source_type: payload.source_type,
    source_mode: 'snapshot',
    retrieval_mode: payload.retrieval_mode,
    description: payload.description ?? '',
    sync_mode: payload.sync_mode,
    sync_schedule: payload.sync_schedule,
    last_synced_at: null,
    status: 'pending',
    citations_enabled: payload.citations_enabled,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  })
)

const uploadFileMock = vi.fn(
  async (_args: { file: File }): Promise<UploadFileResult> => ({
    object_key: 'objects/test.pdf',
  })
)

vi.mock('@/hooks/use-create-source', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-create-source')>()
  return {
    ...actual,
    useCreateSource: () => ({
      mutate: (
        payload: CreateSourcePayload,
        opts?: {
          onSuccess?: (result: CreatedSource) => void
          onError?: (err: Error) => void
        }
      ) => {
        createSourceMock(payload)
          .then((res) => opts?.onSuccess?.(res))
          .catch((err: unknown) => opts?.onError?.(err instanceof Error ? err : new Error('boom')))
      },
      isPending: false,
    }),
  }
})

vi.mock('@/hooks/use-upload-url', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-upload-url')>()
  return {
    ...actual,
    useUploadFile: () => ({
      mutateAsync: (args: { file: File }) => uploadFileMock(args),
    }),
  }
})

// EmbedderPicker hits a query — short-circuit it.
vi.mock('@/components/admin/EmbedderPicker', () => ({
  EmbedderPicker: () => <div data-testid="embedder-picker-stub" />,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER mocks so the page picks them up.
import NewSourcePage from '../page'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<NewSourcePage />, { wrapper: Wrapper })
}

async function uploadOneFile() {
  const file = new File(['hello'], 'note.pdf', { type: 'application/pdf' })
  const input = screen.getByLabelText('Upload files') as HTMLInputElement
  const user = userEvent.setup()
  await user.upload(input, file)
  // Wait for the optimistic queue to drain through the mocked upload.
  // Use the row's status `<span>Uploaded</span>` (exact match) to avoid
  // colliding with the summary's "1 uploaded" text.
  await waitFor(() => {
    expect(screen.getByText('Uploaded', { selector: 'span' })).toBeInTheDocument()
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NewSourcePage — AI-naming checkbox', () => {
  beforeEach(() => {
    createSourceMock.mockClear()
    uploadFileMock.mockClear()
  })

  it('defaults the checkbox to UNchecked and keeps fields enabled', () => {
    renderPage()

    const checkbox = screen.getByRole('checkbox', {
      name: /let ai name and describe this source for me/i,
    })
    expect(checkbox.getAttribute('aria-checked')).toBe('false')

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    const descInput = screen.getByLabelText(/^description \(optional\)$/i) as HTMLTextAreaElement

    expect(nameInput.disabled).toBe(false)
    expect(descInput.disabled).toBe(false)
  })

  it('blocks submit with a "Name is required" error when checkbox is unchecked and name is empty', async () => {
    const user = userEvent.setup()
    renderPage()
    await uploadOneFile()

    await user.click(screen.getByRole('button', { name: /create source/i }))

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument()
    expect(createSourceMock).not.toHaveBeenCalled()
  })

  it('disables both fields, relaxes validation, and submits auto=true with empty name when checked', async () => {
    const user = userEvent.setup()
    renderPage()
    await uploadOneFile()

    const checkbox = screen.getByRole('checkbox', {
      name: /let ai name and describe this source for me/i,
    })
    await user.click(checkbox)
    expect(checkbox.getAttribute('aria-checked')).toBe('true')

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    const descInput = screen.getByLabelText(/^description \(optional\)$/i) as HTMLTextAreaElement

    expect(nameInput.disabled).toBe(true)
    expect(descInput.disabled).toBe(true)
    expect(nameInput.placeholder).toMatch(/AI will pick a name after ingestion/i)
    expect(descInput.placeholder).toMatch(/AI will write a description after ingestion/i)

    await user.click(screen.getByRole('button', { name: /create source/i }))

    await waitFor(() => {
      expect(createSourceMock).toHaveBeenCalledTimes(1)
    })
    const payload = createSourceMock.mock.calls[0]?.[0]
    expect(payload).toBeDefined()
    expect(payload?.auto_name_and_description).toBe(true)
    expect(payload?.name).toBe('')
    expect(payload?.description).toBe('')
  })

  it('clears any drafted name/description when the checkbox is checked', async () => {
    const user = userEvent.setup()
    renderPage()

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    const descInput = screen.getByLabelText(/^description \(optional\)$/i) as HTMLTextAreaElement
    await user.type(nameInput, 'My draft name')
    await user.type(descInput, 'My draft description')
    expect(nameInput.value).toBe('My draft name')

    await user.click(
      screen.getByRole('checkbox', {
        name: /let ai name and describe this source for me/i,
      })
    )

    await waitFor(() => {
      expect(nameInput.value).toBe('')
      expect(descInput.value).toBe('')
    })
  })

  it('re-tightens validation when the checkbox is unchecked again', async () => {
    const user = userEvent.setup()
    renderPage()
    await uploadOneFile()

    const checkbox = screen.getByRole('checkbox', {
      name: /let ai name and describe this source for me/i,
    })
    // Toggle on, then off — fields are now empty but enabled.
    await user.click(checkbox)
    await user.click(checkbox)
    expect(checkbox.getAttribute('aria-checked')).toBe('false')

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    expect(nameInput.disabled).toBe(false)

    await user.click(screen.getByRole('button', { name: /create source/i }))

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument()
    expect(createSourceMock).not.toHaveBeenCalled()
  })
})
