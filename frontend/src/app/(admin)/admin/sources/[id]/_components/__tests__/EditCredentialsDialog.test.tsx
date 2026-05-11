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
  SourceConnectionConfig,
  SourceDetail,
  UpdateSourceCredentialsRequest,
} from '@/lib/api/sources'

// Mock the API module BEFORE the SUT imports it.
const updateSourceCredentialsMock =
  vi.fn<(id: string, body: UpdateSourceCredentialsRequest) => Promise<SourceDetail>>()
const getSourceConnectionConfigMock =
  vi.fn<(id: string) => Promise<SourceConnectionConfig>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    updateSourceCredentialsApi: (
      id: string,
      body: UpdateSourceCredentialsRequest
    ) => updateSourceCredentialsMock(id, body),
    getSourceConnectionConfigApi: (id: string) =>
      getSourceConnectionConfigMock(id),
  }
})

function makeConnectionConfig(
  overrides: Partial<SourceConnectionConfig> = {}
): SourceConnectionConfig {
  return {
    db_type: 'postgresql',
    host: 'reporting.example.com',
    port: 5432,
    database: 'analytics',
    username: 'report_ro',
    ssl_mode: 'require',
    collection: null,
    query: 'SELECT * FROM v_report',
    has_password: true,
    ...overrides,
  }
}

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
  getSourceConnectionConfigMock.mockReset()
  // Default: a fully-populated config so the form pre-fills on open.
  getSourceConnectionConfigMock.mockResolvedValue(makeConnectionConfig())
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wait until the host input has been pre-filled from the fetched config. */
async function waitForPrefill(value: string): Promise<void> {
  await waitFor(() => {
    expect(screen.getByTestId('cred-host')).toHaveValue(value)
  })
}

/** Replace an input's full value (clear + type) — pre-fill makes type() append. */
async function setInput(
  user: ReturnType<typeof userEvent.setup>,
  testId: string,
  value: string
): Promise<void> {
  const el = screen.getByTestId(testId)
  await user.clear(el)
  if (value.length > 0) await user.type(el, value)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('EditCredentialsDialog — re-auth gate (FX4)', () => {
  it('renders a confirm-password field of type=password', async () => {
    renderDialog()
    const confirm = screen.getByTestId('cred-confirm-password')
    expect(confirm).toBeInTheDocument()
    expect(confirm).toHaveAttribute('type', 'password')
    await waitForPrefill('reporting.example.com')
  })

  it('the new-password field is also type=password', async () => {
    renderDialog()
    const password = screen.getByTestId('cred-password')
    expect(password).toHaveAttribute('type', 'password')
    await waitForPrefill('reporting.example.com')
  })

  it('blocks submit when confirm_password is blank', async () => {
    const user = userEvent.setup()
    renderDialog()
    await waitForPrefill('reporting.example.com')

    // Change host so there's a field to save; confirm_password left blank.
    await setInput(user, 'cred-host', 'new.example.com')
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(screen.getByTestId('edit-credentials-error')).toHaveTextContent(
        /confirm your password/i
      )
    })
    expect(updateSourceCredentialsMock).not.toHaveBeenCalled()
  })
})

describe('EditCredentialsDialog — pre-fill (FX7)', () => {
  it('pre-fills host/port/database/username from the fetched config', async () => {
    renderDialog()
    await waitForPrefill('reporting.example.com')
    expect(screen.getByTestId('cred-port')).toHaveValue('5432')
    expect(screen.getByTestId('cred-database')).toHaveValue('analytics')
    expect(screen.getByTestId('cred-username')).toHaveValue('report_ro')
    // Config fetch was scoped to this source id.
    expect(getSourceConnectionConfigMock).toHaveBeenCalledWith('src-db-1')
  })

  it('leaves the password input empty and shows the "unchanged" placeholder', async () => {
    renderDialog()
    await waitForPrefill('reporting.example.com')
    const password = screen.getByTestId('cred-password')
    expect(password).toHaveValue('')
    expect(password).toHaveAttribute(
      'placeholder',
      expect.stringMatching(/unchanged/i)
    )
    expect(screen.getByTestId('cred-password-help')).toHaveTextContent(
      /leave blank to keep it/i
    )
  })

  it('shows the "no password set" placeholder when has_password is false', async () => {
    getSourceConnectionConfigMock.mockResolvedValue(
      makeConnectionConfig({ has_password: false })
    )
    renderDialog()
    await waitForPrefill('reporting.example.com')
    const password = screen.getByTestId('cred-password')
    expect(password).toHaveAttribute(
      'placeholder',
      expect.stringMatching(/no password set/i)
    )
  })

  it('still lets the admin fill the form when the config fetch fails', async () => {
    const user = userEvent.setup()
    getSourceConnectionConfigMock.mockRejectedValue(new Error('boom'))
    renderDialog()

    await waitFor(() => {
      expect(
        screen.getByTestId('edit-credentials-config-error')
      ).toBeInTheDocument()
    })
    // Form is usable — host starts empty and is editable.
    const host = screen.getByTestId('cred-host')
    expect(host).toHaveValue('')
    await user.type(host, 'fallback.example.com')
    expect(host).toHaveValue('fallback.example.com')
  })
})

describe('EditCredentialsDialog — submit diffs against fetched config', () => {
  it('sends ONLY confirm_password when nothing changed', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockResolvedValue(makeSource())
    const { onOpenChange } = renderDialog()
    await waitForPrefill('reporting.example.com')

    // Touch nothing but the re-auth field.
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
    expect(calledBody).toEqual({ confirm_password: 'AdminOwnPw!23' })

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false)
    })
  })

  it('sends { host, confirm_password } when only host changed', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockResolvedValue(makeSource())
    renderDialog()
    await waitForPrefill('reporting.example.com')

    await setInput(user, 'cred-host', 'new.example.com')
    await user.type(
      screen.getByTestId('cred-confirm-password'),
      'AdminOwnPw!23'
    )
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(updateSourceCredentialsMock).toHaveBeenCalledTimes(1)
    })
    const [, calledBody] = updateSourceCredentialsMock.mock.calls[0]!
    expect(calledBody).toEqual({
      host: 'new.example.com',
      confirm_password: 'AdminOwnPw!23',
    })
  })

  it('includes password ONLY when the admin typed one', async () => {
    const user = userEvent.setup()
    updateSourceCredentialsMock.mockResolvedValue(makeSource())
    renderDialog()
    await waitForPrefill('reporting.example.com')

    await user.type(screen.getByTestId('cred-password'), 'rotated-pw')
    await user.type(
      screen.getByTestId('cred-confirm-password'),
      'AdminOwnPw!23'
    )
    await user.click(screen.getByTestId('edit-credentials-save'))

    await waitFor(() => {
      expect(updateSourceCredentialsMock).toHaveBeenCalledTimes(1)
    })
    const [, calledBody] = updateSourceCredentialsMock.mock.calls[0]!
    expect(calledBody).toEqual({
      password: 'rotated-pw',
      confirm_password: 'AdminOwnPw!23',
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
    await waitForPrefill('reporting.example.com')

    await setInput(user, 'cred-host', 'broken.example.com')
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
    await waitForPrefill('reporting.example.com')

    await setInput(user, 'cred-host', 'new.example.com')
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
