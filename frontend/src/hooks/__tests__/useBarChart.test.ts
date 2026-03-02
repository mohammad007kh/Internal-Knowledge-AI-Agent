import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useBarChart } from '../useBarChart'

describe('useBarChart', () => {
  it('returns a canvas ref', () => {
    const { result } = renderHook(() => useBarChart([{ label: '2024-01-01', value: 5 }]))

    expect(result.current).toBeDefined()
    expect(result.current.current).toBeNull()
  })
})
