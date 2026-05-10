import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AuditLogTable } from '../AuditLogTable'
import type { AuditLogEntry } from '@/lib/api/audit-log'

function buildEntry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id: '1',
    created_at: '2026-01-02T03:04:05Z',
    action: 'source.create',
    resource_type: 'source',
    resource_id: '11111111-2222-3333-4444-555555555555',
    admin_user_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    admin_user_email: 'alice@example.com',
    metadata: { name: 'Acme', extra: 'value' },
    ip_address: '127.0.0.1',
    user_agent: null,
    ...overrides,
  }
}

describe('AuditLogTable', () => {
  it('renders a row per entry with actor email and action chip', () => {
    const entries = [
      buildEntry({ id: '1', admin_user_email: 'alice@example.com' }),
      buildEntry({
        id: '2',
        admin_user_email: 'bob@example.com',
        action: 'login_success',
        resource_type: 'user',
      }),
    ]
    render(
      <AuditLogTable
        items={entries}
        total={2}
        page={1}
        pageSize={50}
        onPageChange={() => {}}
      />
    )

    const rows = screen.getAllByTestId('audit-log-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('alice@example.com')).toBeInTheDocument()
    expect(within(rows[0]).getByText('source.create')).toBeInTheDocument()
    expect(within(rows[1]).getByText('bob@example.com')).toBeInTheDocument()
    expect(within(rows[1]).getByText('login_success')).toBeInTheDocument()
  })

  it('renders "system" when admin_user_email is null', () => {
    render(
      <AuditLogTable
        items={[buildEntry({ admin_user_email: null, admin_user_id: null })]}
        total={1}
        page={1}
        pageSize={50}
        onPageChange={() => {}}
      />
    )
    expect(screen.getByText('system')).toBeInTheDocument()
  })

  it('truncates resource_id and exposes a copy button', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    render(
      <AuditLogTable
        items={[
          buildEntry({
            resource_id: '11111111-2222-3333-4444-555555555555',
          }),
        ]}
        total={1}
        page={1}
        pageSize={50}
        onPageChange={() => {}}
      />
    )

    // The 12-char truncation uses an ellipsis, not the full UUID.
    expect(screen.getByText('11111111…5555')).toBeInTheDocument()
    expect(screen.queryByText('11111111-2222-3333-4444-555555555555')).toBeNull()

    await user.click(screen.getByTestId('copy-id-button'))
    expect(writeText).toHaveBeenCalledWith('11111111-2222-3333-4444-555555555555')
  })

  it('expands metadata when clicked and collapses on second click', () => {
    render(
      <AuditLogTable
        items={[buildEntry({ metadata: { name: 'Acme', extra: 'value' } })]}
        total={1}
        page={1}
        pageSize={50}
        onPageChange={() => {}}
      />
    )

    const toggle = screen.getByTestId('metadata-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    // Pretty-printed JSON contains the doublespace + double-quoted key.
    expect(toggle.textContent).toContain('"name": "Acme"')

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('hides the pagination footer when total <= pageSize', () => {
    const onPageChange = vi.fn()
    render(
      <AuditLogTable
        items={[buildEntry()]}
        total={1}
        page={1}
        pageSize={50}
        onPageChange={onPageChange}
      />
    )
    expect(screen.queryByTestId('audit-log-prev')).toBeNull()
    expect(screen.queryByTestId('audit-log-next')).toBeNull()
  })

  it('renders the pagination footer and disables Previous on page 1', () => {
    const onPageChange = vi.fn()
    render(
      <AuditLogTable
        items={[buildEntry()]}
        total={123}
        page={1}
        pageSize={50}
        onPageChange={onPageChange}
      />
    )
    expect(screen.getByTestId('audit-log-prev')).toBeDisabled()
    expect(screen.getByTestId('audit-log-next')).not.toBeDisabled()
    fireEvent.click(screen.getByTestId('audit-log-next'))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('disables Next on the last page', () => {
    render(
      <AuditLogTable
        items={[buildEntry()]}
        total={50 * 3}
        page={3}
        pageSize={50}
        onPageChange={() => {}}
      />
    )
    expect(screen.getByTestId('audit-log-next')).toBeDisabled()
    expect(screen.getByTestId('audit-log-prev')).not.toBeDisabled()
  })

  it('renders an em dash for null resource_id and ip_address', () => {
    render(
      <AuditLogTable
        items={[
          buildEntry({
            resource_id: null,
            ip_address: null,
          }),
        ]}
        total={1}
        page={1}
        pageSize={50}
        onPageChange={() => {}}
      />
    )
    // Two em-dashes — one for the resource_id cell (italic) and one for IP.
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(2)
  })
})
