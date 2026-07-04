/**
 * OverviewCallouts — failed schema-study surfacing (DB connect-retry Slice 5b).
 *
 * The categorised connection-failure fields (failure_headline / next_action /
 * attempts_made) render as a destructive callout; a non-connection study
 * failure falls back to a generic one; a study failure suppresses the
 * duplicate sync-failed box for DB sources.
 */
import type { SourceDetail } from '@/lib/api/sources'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { OverviewCallouts } from '../OverviewCards'

function makeSource(overrides: Partial<SourceDetail>): SourceDetail {
  return overrides as unknown as SourceDetail
}

describe('OverviewCallouts — failed schema study', () => {
  it('renders a categorised connection-failure callout with next_action + attempts', () => {
    render(
      <OverviewCallouts
        source={makeSource({
          study_state: 'CONNECT_FAILED',
          failure_category: 'DB_UNREACHABLE',
          failure_headline: 'The database could not be reached.',
          failure_next_action: 'Confirm the database is running and reachable.',
          attempts_made: 3,
        })}
        isDbSource
        onRetrySync={vi.fn()}
      />
    )
    expect(screen.getByText('The database could not be reached.')).toBeTruthy()
    expect(screen.getByText(/Confirm the database is running/)).toBeTruthy()
    expect(screen.getByText(/Failed after 3 connection attempts\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Re-test connection' })).toBeTruthy()
  })

  it('suppresses the attempt suffix on fail-fast (attempts_made === 1)', () => {
    render(
      <OverviewCallouts
        source={makeSource({
          study_state: 'CONNECT_FAILED',
          failure_category: 'AUTH_FAILED',
          failure_headline: 'The database rejected the credentials.',
          failure_next_action: 'Update the username and password, then re-test.',
          attempts_made: 1,
        })}
        isDbSource
        onRetrySync={vi.fn()}
      />
    )
    expect(screen.getByText('The database rejected the credentials.')).toBeTruthy()
    expect(screen.queryByText(/Failed after/)).toBeNull()
  })

  it('falls back to a generic study-failed callout for non-connection failures', () => {
    render(
      <OverviewCallouts
        source={makeSource({
          study_state: 'INVENTORY_FAILED',
          failure_category: null,
          failure_headline: null,
          last_error_message: 'Reflection of the schema list failed.',
        })}
        isDbSource
        onRetrySync={vi.fn()}
      />
    )
    expect(screen.getByText('Schema study failed')).toBeTruthy()
    expect(screen.getByText('Reflection of the schema list failed.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Re-study' })).toBeTruthy()
  })

  it('suppresses the duplicate sync-failed callout when the study failed', () => {
    render(
      <OverviewCallouts
        source={makeSource({
          study_state: 'CONNECT_FAILED',
          failure_headline: 'The database rejected the credentials.',
          failure_next_action: 'Update the credentials, then re-test.',
          attempts_made: 1,
          latest_job: {
            status: 'failed',
            error_message: 'sync boom',
          } as SourceDetail['latest_job'],
        })}
        isDbSource
        onRetrySync={vi.fn()}
      />
    )
    expect(screen.queryByText('Last sync failed')).toBeNull()
    expect(screen.getByText('The database rejected the credentials.')).toBeTruthy()
  })

  it('renders nothing for a healthy DB source', () => {
    const { container } = render(
      <OverviewCallouts
        source={makeSource({ study_state: 'READY' })}
        isDbSource
        onRetrySync={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })
})
