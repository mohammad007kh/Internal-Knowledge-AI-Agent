import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AuditLogToolbar } from '../AuditLogToolbar'
import type {
  ActiveChip,
  AuditLogFilterState,
} from '../useAuditLogFilters'

// Radix Select pointer-capture stubs live in src/test/setup.ts.

function buildState(overrides: Partial<AuditLogFilterState> = {}): AuditLogFilterState {
  return {
    search: '',
    action: '',
    resourceType: '',
    adminUserId: '',
    from: '',
    to: '',
    page: 1,
    pageSize: 50,
    ...overrides,
  }
}

interface RenderArgs {
  state?: Partial<AuditLogFilterState>
  onChange?: (
    updater: (prev: AuditLogFilterState) => AuditLogFilterState
  ) => void
  activeChips?: readonly ActiveChip[]
  onClearAll?: () => void
}

function renderToolbar(args: RenderArgs = {}) {
  const onChange = args.onChange ?? vi.fn()
  const onClearAll = args.onClearAll ?? vi.fn()
  const state = buildState(args.state)
  render(
    <AuditLogToolbar
      state={state}
      onChange={onChange}
      activeChips={args.activeChips ?? []}
      onClearAll={onClearAll}
      totalCount={100}
      filteredCount={100}
    />
  )
  return { onChange, onClearAll, state }
}

describe('AuditLogToolbar action dropdown', () => {
  it('emits the fully-qualified ai_model.create when that option is picked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn<
      [(prev: AuditLogFilterState) => AuditLogFilterState],
      void
    >()
    renderToolbar({ onChange })

    const trigger = screen.getByLabelText('Filter by action')
    await user.click(trigger)

    // Radix renders options into a portal; we look up by accessible name.
    const option = await screen.findByRole('option', { name: 'ai_model.create' })
    await user.click(option)

    expect(onChange).toHaveBeenCalled()
    const updater = onChange.mock.calls[0][0]
    const next = updater(buildState())
    // Regression: the dropdown value MUST be the full dotted action string,
    // NOT the bare verb 'create'. A bare verb would silently match every
    // resource_type's 'create' rows (e.g. source.create) and produce the
    // wrong page.
    expect(next.action).toBe('ai_model.create')
    expect(next.action).not.toBe('create')
    expect(next.page).toBe(1)
  })

  it.each([
    ['ai_model.update'],
    ['ai_model.delete'],
    ['ai_model.test'],
  ])(
    'emits the fully-qualified %s when that option is picked',
    async (expectedAction) => {
      const user = userEvent.setup()
      const onChange = vi.fn<
        [(prev: AuditLogFilterState) => AuditLogFilterState],
        void
      >()
      renderToolbar({ onChange })

      const trigger = screen.getByLabelText('Filter by action')
      await user.click(trigger)

      const option = await screen.findByRole('option', { name: expectedAction })
      await user.click(option)

      const updater = onChange.mock.calls[0][0]
      const next = updater(buildState())
      expect(next.action).toBe(expectedAction)
    }
  )

  it('All actions sentinel clears the filter', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn<
      [(prev: AuditLogFilterState) => AuditLogFilterState],
      void
    >()
    renderToolbar({ state: { action: 'ai_model.create' }, onChange })

    const trigger = screen.getByLabelText('Filter by action')
    await user.click(trigger)

    const option = await screen.findByRole('option', { name: 'All actions' })
    await user.click(option)

    const updater = onChange.mock.calls[0][0]
    const next = updater(buildState({ action: 'ai_model.create' }))
    expect(next.action).toBe('')
  })
})
