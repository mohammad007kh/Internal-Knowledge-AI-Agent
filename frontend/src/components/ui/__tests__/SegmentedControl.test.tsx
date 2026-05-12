import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SegmentedControl } from '../segmented-control'

const OPTIONS = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
] as const

describe('SegmentedControl', () => {
  it('renders one button per option and marks the active one', () => {
    render(<SegmentedControl label="Range" options={OPTIONS} value="7d" onChange={() => {}} />)
    const group = screen.getByRole('group', { name: 'Range' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '30d' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('fires onChange with the option value when a segment is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<SegmentedControl label="Range" options={OPTIONS} value="7d" onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: '30d' }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('30d')
  })

  it('renders the label prefix unless hideLabel is set', () => {
    const { rerender } = render(
      <SegmentedControl label="Status" options={OPTIONS} value="7d" onChange={() => {}} />
    )
    expect(screen.getByText('Status:')).toBeInTheDocument()
    rerender(<SegmentedControl label="Status" options={OPTIONS} value="7d" onChange={() => {}} hideLabel />)
    expect(screen.queryByText('Status:')).not.toBeInTheDocument()
  })
})
