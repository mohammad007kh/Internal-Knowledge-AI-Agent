/**
 * LifecycleProgressBar — FX16 admin-visible progress.
 *
 * The bar must:
 *   - render while the source is in flight (pending_upload / naming / chunking
 *     / analyzing),
 *   - render as indeterminate for pending_upload (no real % to show),
 *   - render with a numeric percent for naming / chunking / analyzing,
 *   - collapse to nothing once the source reaches ready or failed.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LifecycleProgressBar } from '../LifecycleProgressBar'

describe('LifecycleProgressBar', () => {
  it('renders nothing when phase is ready', () => {
    const { container } = render(<LifecycleProgressBar phase="ready" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when phase is failed', () => {
    const { container } = render(<LifecycleProgressBar phase="failed" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders an indeterminate bar for pending_upload', () => {
    render(<LifecycleProgressBar phase="pending_upload" />)
    const bar = screen.getByTestId('lifecycle-progress-bar')
    expect(bar).toHaveAttribute('data-indeterminate', 'true')
    // No numeric percent should be shown for the indeterminate state.
    expect(screen.queryByTestId('lifecycle-progress-percent')).toBeNull()
  })

  it('renders a determinate bar with a percent for naming', () => {
    render(<LifecycleProgressBar phase="naming" />)
    const bar = screen.getByTestId('lifecycle-progress-bar')
    expect(bar).toHaveAttribute('data-indeterminate', 'false')
    expect(screen.getByTestId('lifecycle-progress-percent').textContent).toMatch(/\d+%/)
  })

  it('renders a determinate bar with a percent for analyzing', () => {
    render(<LifecycleProgressBar phase="analyzing" />)
    expect(screen.getByTestId('lifecycle-progress-percent').textContent).toMatch(
      /\d+%/
    )
  })

  it('renders the optional detail line when provided', () => {
    render(<LifecycleProgressBar phase="chunking" detail="started just now" />)
    expect(screen.getByTestId('lifecycle-progress-detail')).toHaveTextContent(
      'started just now'
    )
  })

  it('progressbar has correct aria attributes', () => {
    render(<LifecycleProgressBar phase="analyzing" />)
    const pb = screen.getByRole('progressbar')
    expect(pb).toHaveAttribute('aria-valuemin', '0')
    expect(pb).toHaveAttribute('aria-valuemax', '100')
    expect(pb).toHaveAttribute('aria-valuenow')
  })

  it('progressbar omits aria-valuenow when indeterminate', () => {
    render(<LifecycleProgressBar phase="pending_upload" />)
    const pb = screen.getByRole('progressbar')
    expect(pb).not.toHaveAttribute('aria-valuenow')
  })
})
