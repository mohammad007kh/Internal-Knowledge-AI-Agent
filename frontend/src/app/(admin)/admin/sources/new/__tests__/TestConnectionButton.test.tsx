/**
 * "Test connection" button — wires the database step of /admin/sources/new
 * to POST /api/v1/sources/inspect (the pre-persistence connectivity check).
 *
 * Coverage:
 *   1. Button is disabled when host (and other required fields) are empty.
 *   2. Button enables once every required connection field is filled.
 *   3. Click invokes `inspectSourceApi` with the expected
 *      {source_type: 'database', connection: {...}} payload.
 *   4. Success state renders the returned description.
 *   5. Error state renders the API error message.
 *
 * Result is diagnostic only — the form's name + description fields must
 * remain user-controlled (untouched by the inspect response).
 */

import type { CreatedSource, CreateSourcePayload } from '@/hooks/use-create-source'
import type { UploadFileResult } from '@/hooks/use-upload-url'
import type { InspectSourceRequest, InspectSourceResponse } from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks — registered BEFORE the page is imported.
// ---------------------------------------------------------------------------

const inspectSourceMock = vi.fn(
  async (_body: InspectSourceRequest): Promise<InspectSourceResponse> => ({
    description: '',
    schema_summary: {},
  })
)

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    inspectSourceApi: (body: InspectSourceRequest) => inspectSourceMock(body),
  }
})

// The page imports useCreateSource + useUploadFile; we never actually submit
// the form in this suite, but the page still renders the hooks at module
// load. Stub them so they never hit the network.
vi.mock('@/hooks/use-create-source', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-create-source')>()
  return {
    ...actual,
    useCreateSource: () => ({
      mutate: (
        _payload: CreateSourcePayload,
        _opts?: {
          onSuccess?: (result: CreatedSource) => void
          onError?: (err: Error) => void
        }
      ) => {
        /* not invoked in this suite */
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
      mutateAsync: async (_args: { file: File }): Promise<UploadFileResult> => ({
        object_key: 'objects/test.pdf',
      }),
    }),
  }
})

// EmbedderPicker hits a query under the hood — short-circuit it.
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

async function selectDatabaseSourceType() {
  const user = userEvent.setup()
  const radio = screen.getByRole('radio', { name: /database/i })
  await user.click(radio)
  return user
}

function getTestButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /test connection/i }) as HTMLButtonElement
}

async function fillRequiredDatabaseFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/^host$/i), 'db.example.com')
  // Port has a default (5432). Fields are filled by typing on top of the
  // default value, but we only need username/password/database_name typed.
  await user.type(screen.getByLabelText(/^database name$/i), 'analytics')
  await user.type(screen.getByLabelText(/^username \(optional\)$/i), 'reader')
  await user.type(screen.getByLabelText(/^password \(optional\)$/i), 's3cret')
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NewSourcePage — Test connection button', () => {
  beforeEach(() => {
    inspectSourceMock.mockReset()
  })

  it('is disabled when host is empty (and other required fields missing)', async () => {
    renderPage()
    await selectDatabaseSourceType()

    const btn = getTestButton()
    expect(btn).toBeDisabled()

    expect(inspectSourceMock).not.toHaveBeenCalled()
  })

  it('enables once host, port, database name, username, and password are filled', async () => {
    renderPage()
    const user = await selectDatabaseSourceType()

    expect(getTestButton()).toBeDisabled()

    await fillRequiredDatabaseFields(user)

    await waitFor(() => {
      expect(getTestButton()).not.toBeDisabled()
    })
  })

  it('calls inspectSourceApi with source_type=database and the typed connection', async () => {
    inspectSourceMock.mockResolvedValueOnce({
      description: 'PostgreSQL `analytics` — 12 tables.',
      schema_summary: { table_count: 12, estimated_row_count: 0 },
    })

    renderPage()
    const user = await selectDatabaseSourceType()
    await fillRequiredDatabaseFields(user)

    await user.click(getTestButton())

    await waitFor(() => {
      expect(inspectSourceMock).toHaveBeenCalledTimes(1)
    })
    const body = inspectSourceMock.mock.calls[0]?.[0]
    expect(body?.source_type).toBe('database')
    expect(body?.connection).toMatchObject({
      db_type: 'postgresql',
      host: 'db.example.com',
      port: 5432,
      database: 'analytics',
      username: 'reader',
      password: 's3cret',
      ssl_mode: 'disable',
    })
  })

  it('renders the returned description on success', async () => {
    const description = 'PostgreSQL `analytics` — 12 tables of customer data.'
    inspectSourceMock.mockResolvedValueOnce({
      description,
      schema_summary: {},
    })

    renderPage()
    const user = await selectDatabaseSourceType()
    await fillRequiredDatabaseFields(user)
    await user.click(getTestButton())

    const success = await screen.findByTestId('test-connection-success')
    expect(success).toHaveTextContent(description)
    // Diagnostic only: the user-typed name + description fields stay empty.
    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    const descInput = screen.getByLabelText(/^description \(optional\)$/i) as HTMLTextAreaElement
    expect(nameInput.value).toBe('')
    expect(descInput.value).toBe('')
  })

  it('renders the API error message on failure', async () => {
    inspectSourceMock.mockRejectedValueOnce(
      new Error('Could not connect to database source')
    )

    renderPage()
    const user = await selectDatabaseSourceType()
    await fillRequiredDatabaseFields(user)
    await user.click(getTestButton())

    const errorBox = await screen.findByTestId('test-connection-error')
    expect(errorBox).toHaveTextContent(/could not connect to database source/i)
  })

  it('surfaces the backend RFC-7807 detail from a raw axios-shaped error (FX13)', async () => {
    // The interceptor doesn't always flatten problem+json (content-type
    // mismatch / direct apiClient call), so the raw AxiosError reaches the
    // caller with the useless generic `.message`. The wizard must dig the
    // backend's `detail` out of `response.data` instead.
    inspectSourceMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          type: 'about:blank',
          title: 'Unprocessable Entity',
          status: 422,
          detail: 'Could not connect to database source',
        },
      },
    })

    renderPage()
    const user = await selectDatabaseSourceType()
    await fillRequiredDatabaseFields(user)
    await user.click(getTestButton())

    const errorBox = await screen.findByTestId('test-connection-error')
    expect(errorBox).toHaveTextContent(/could not connect to database source/i)
    expect(errorBox).not.toHaveTextContent(/request failed with status code/i)
  })

  it('surfaces the nested HTTPException(detail={...}) message (FX13)', async () => {
    inspectSourceMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: {
            type: 'about:blank',
            title: 'Unprocessable Entity',
            status: 422,
            detail: 'Connection test failed with the supplied credentials.',
          },
        },
      },
    })

    renderPage()
    const user = await selectDatabaseSourceType()
    await fillRequiredDatabaseFields(user)
    await user.click(getTestButton())

    const errorBox = await screen.findByTestId('test-connection-error')
    expect(errorBox).toHaveTextContent(/connection test failed with the supplied credentials/i)
    expect(errorBox).not.toHaveTextContent(/request failed with status code/i)
  })
})
