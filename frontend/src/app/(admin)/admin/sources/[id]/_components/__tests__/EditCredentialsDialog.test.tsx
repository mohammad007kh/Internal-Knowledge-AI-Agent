/**
 * EditCredentialsDialog (U8 + FX4) — admin credential rotation dialog.
 *
 * Verifies:
 *   - The dialog renders with the password-confirm field present and
 *     marked as type=password.
 *   - On happy-path submit, the API client is called with the structured
 *     payload AND the confirm_password is forwarded to the backend.
 *   - On API error (401 wrong password OR 422 connector failure), the
 *     dialog stays open and renders the error inline — never silently
 *     swallows or auto-closes.
 *
 * The actual re-auth gate + connector test live on the backend; the front
 * end's job is to surface the 401/422 messages and not leak credentials.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  SourceDetail,
  UpdateSourceCredentialsRequest,
} from '@/lib/api/sources'

// Mock the API module BEFORE the SUT imports it.
const updateSourceCredentialsMock =
  vi.fn<(id: string, body: UpdateSourceCredentialsRequest) => Promise<SourceDetail>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    updateSourceCredentialsApi: (
      id: string,
      body: UpdateSourceCredentialsRequest
    ) => updateSourceCredentialsMock(id, body),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { EditCredentialsDialog } from '../EditCredentialsDialog'

// ---------------------------------------------------------------------------
// Fixtures + render helper
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-db-1',
    name: 'Reporting DB',
    source_type: 'database',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'live',
    retrieval_mode: 'text_to_query',
    description: 'Postgres reporting',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-05-08T00:00:00Z',
    connection_status: 'healthy',
    ...overrides,
  } as SourceDetail
}

function renderDialog(source: SourceDetail = makeSource()): {
  onOpenChange: ReturnType<typeof vi.fn>
} {
  const onOpenChange = vi.fn<(open: boolean) => void>()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  render(
    <EditCredentialsDialog
      source={source}
      open={true}
      onOpenChange={onOpenChange}
    />,
    { wrapper: Wrapper }
  )
  return { onOpenChange }
}

beforeEach(() => {
  updateSourceCredentialsMock.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('EditCredentialsDialog — re-auth gate (FX4)', () => {
  it('renders a confirm-password field of type=password', () => {
    renderDialog()
    const confirm = screen.getByTestId('cred-confirm-password')
    expect(confirm).toBeInTheDocument()
    expect(confirm).toHaveAttribute('type', 'password')
  })

  it('the new-password field is also type=password', () => {
    renderDialog()
    const password = screen.getByTestId('cred-password')
    expect(password).toHaveAttribute('type', 'password')
  })

  it('blocks submit when confirm_password is blank', async () => {
    const user = userEvent.setup()
    renderDialog()

    // Type something in host so the "no fields changed" check passes.
    await user.type(screen.getByTestId('cred-host'), 'new.example.com')
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(screen.getByTestId('edit-credentials-error')).toHaveTextContent(
        /confirm your password/i
      )
    })
    expect(updateSourceCredentialsMock).not.toHaveBeenCalled()
  })
})

describe('EditCredentialsDialog — happy path', () => {
  it('forwards structured payload + confirm_password to the API', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockResolvedValue(makeSource())
    const { onOpenChange } = renderDialog()

    await user.type(screen.getByTestId('cred-host'), 'new.example.com')
    await user.type(screen.getByTestId('cred-port'), '5433')
    await user.type(screen.getByTestId('cred-password'), 'newpw-secret')
    await user.type(
      screen.getByTestId('cred-confirm-password'),
      'AdminOwnPw!23'
    )
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(updateSourceCredentialsMock).toHaveBeenCalledTimes(1)
    })
    const [calledId, calledBody] = updateSourceCredentialsMock.mock.calls[0]!
    expect(calledId).toBe('src-db-1')
    expect(calledBody).toEqual({
      confirm_password: 'AdminOwnPw!23',
      host: 'new.example.com',
      port: 5433,
      password: 'newpw-secret',
    })

    // Dialog closes on success.
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false)
    })
  })
})

describe('EditCredentialsDialog — error rendering', () => {
  it('shows backend error inline and keeps the dialog open', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockRejectedValue(
      new Error('Connection test failed with the supplied credentials.')
    )
    const { onOpenChange } = renderDialog()

    await user.type(screen.getByTestId('cred-host'), 'broken.example.com')
    await user.type(
      screen.getByTestId('cred-confirm-password'),
      'AdminOwnPw!23'
    )
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(screen.getByTestId('edit-credentials-error')).toHaveTextContent(
        /connection test failed/i
      )
    })
    // The dialog stays open — onOpenChange(false) is NOT called on failure.
    const closeCalls = onOpenChange.mock.calls.filter(([open]) => open === false)
    expect(closeCalls).toHaveLength(0)
  })

  it('surfaces a 401 wrong-password error inline', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockRejectedValue(
      new Error('Confirm-password does not match.')
    )
    renderDialog()

    await user.type(screen.getByTestId('cred-host'), 'new.example.com')
    await user.type(
      screen.getByTestId('cred-confirm-password'),
      'wrong-password'
    )
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(screen.getByTestId('edit-credentials-error')).toHaveTextContent(
        /confirm-password does not match/i
      )
    })
  })
})
