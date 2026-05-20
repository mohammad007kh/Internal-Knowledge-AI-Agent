/**
 * FX36 — useUnsavedChangesGuard
 *
 * Verifies both layers (beforeunload + capture-phase anchor click) and the
 * critical cleanup paths so the hook can't leak listeners across remounts.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUnsavedChangesGuard } from '../useUnsavedChangesGuard'

describe('useUnsavedChangesGuard', () => {
  let addWindowSpy: ReturnType<typeof vi.spyOn>
  let removeWindowSpy: ReturnType<typeof vi.spyOn>
  let addDocumentSpy: ReturnType<typeof vi.spyOn>
  let removeDocumentSpy: ReturnType<typeof vi.spyOn>
  let confirmSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    addWindowSpy = vi.spyOn(window, 'addEventListener')
    removeWindowSpy = vi.spyOn(window, 'removeEventListener')
    addDocumentSpy = vi.spyOn(document, 'addEventListener')
    removeDocumentSpy = vi.spyOn(document, 'removeEventListener')
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function countCalls(
    spy: ReturnType<typeof vi.spyOn>,
    event: string
  ): number {
    return spy.mock.calls.filter((args: unknown[]) => args[0] === event).length
  }

  it('registers beforeunload + click listeners only when dirty', () => {
    const { unmount } = renderHook(({ dirty }) => useUnsavedChangesGuard(dirty), {
      initialProps: { dirty: true },
    })

    expect(countCalls(addWindowSpy, 'beforeunload')).toBe(1)
    expect(countCalls(addDocumentSpy, 'click')).toBe(1)

    unmount()
  })

  it('does NOT register listeners when isDirty is false', () => {
    renderHook(() => useUnsavedChangesGuard(false))

    expect(countCalls(addWindowSpy, 'beforeunload')).toBe(0)
    expect(countCalls(addDocumentSpy, 'click')).toBe(0)
  })

  it('tears down listeners when isDirty flips false', () => {
    const { rerender } = renderHook(
      ({ dirty }: { dirty: boolean }) => useUnsavedChangesGuard(dirty),
      { initialProps: { dirty: true } }
    )
    expect(countCalls(addWindowSpy, 'beforeunload')).toBe(1)

    rerender({ dirty: false })

    expect(countCalls(removeWindowSpy, 'beforeunload')).toBe(1)
    expect(countCalls(removeDocumentSpy, 'click')).toBe(1)
  })

  it('tears down listeners on unmount', () => {
    const { unmount } = renderHook(() => useUnsavedChangesGuard(true))
    unmount()

    expect(countCalls(removeWindowSpy, 'beforeunload')).toBe(1)
    expect(countCalls(removeDocumentSpy, 'click')).toBe(1)
  })

  it('beforeunload calls preventDefault when dirty (browser shows native dialog)', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventSpy = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)

    // preventDefault is the modern contract; setting returnValue is the
    // legacy fallback. Asserting preventDefault is enough — jsdom doesn't
    // model returnValue persistence the way real browsers do.
    expect(preventSpy).toHaveBeenCalled()
  })

  it('does NOT register a beforeunload handler that fires when pristine', () => {
    renderHook(() => useUnsavedChangesGuard(false))

    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    const preventSpy = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)

    expect(preventSpy).not.toHaveBeenCalled()
  })

  it('prompts the user when clicking an internal anchor to a new path', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    anchor.dispatchEvent(click)

    expect(confirmSpy).toHaveBeenCalledWith(expect.stringMatching(/unsaved changes/i))
    document.body.removeChild(anchor)
  })

  it('cancels the click when the user declines the prompt', () => {
    confirmSpy.mockReturnValue(false)
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    const preventSpy = vi.spyOn(click, 'preventDefault')
    anchor.dispatchEvent(click)

    expect(preventSpy).toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT cancel the click when the user accepts the prompt', () => {
    confirmSpy.mockReturnValue(true)
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    const preventSpy = vi.spyOn(click, 'preventDefault')
    anchor.dispatchEvent(click)

    expect(preventSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT prompt when form is pristine', () => {
    renderHook(() => useUnsavedChangesGuard(false))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    anchor.dispatchEvent(click)

    expect(confirmSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT prompt for modifier-click (cmd/ctrl/shift) — those open a new tab', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      button: 0,
      ctrlKey: true,
    })
    anchor.dispatchEvent(click)

    expect(confirmSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT prompt for target="_blank" anchors', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    anchor.target = '_blank'
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    anchor.dispatchEvent(click)

    expect(confirmSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT prompt for download anchors', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/files/report.csv'
    anchor.setAttribute('download', 'report.csv')
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    anchor.dispatchEvent(click)

    expect(confirmSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('does NOT prompt for clicks that resolve to the same URL', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = window.location.pathname + window.location.search
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    anchor.dispatchEvent(click)

    expect(confirmSpy).not.toHaveBeenCalled()
    document.body.removeChild(anchor)
  })

  it('prompts when clicking a nested element inside an anchor (closest <a>)', () => {
    renderHook(() => useUnsavedChangesGuard(true))

    const anchor = document.createElement('a')
    anchor.href = '/admin/other'
    const inner = document.createElement('span')
    inner.textContent = 'Nested'
    anchor.appendChild(inner)
    document.body.appendChild(anchor)

    const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    act(() => {
      inner.dispatchEvent(click)
    })

    expect(confirmSpy).toHaveBeenCalled()
    document.body.removeChild(anchor)
  })
})
