/**
 * FileDropzone — native HTML5 drag-and-drop upload target.
 *
 * Covers: drag highlight toggling, drop validation (extension / MIME / size),
 * the empty-MIME-but-good-extension rule, mixed batches, keyboard activation,
 * and the disabled state.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FileDropzone } from '../FileDropzone'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFile(name: string, type: string, size = 8): File {
  const file = new File(['x'.repeat(size)], name, { type })
  // jsdom derives size from the blob parts; pin it explicitly when callers
  // want a specific size without allocating that many bytes.
  Object.defineProperty(file, 'size', { value: size, configurable: true })
  return file
}

function getDropTarget(): HTMLElement {
  return screen.getByRole('button', { name: /upload files/i })
}

/** Build the minimal DataTransfer-ish object RTL needs for a drop event. */
function dataTransferWith(files: readonly File[]) {
  return {
    files,
    items: files.map((file) => ({ kind: 'file', type: file.type, getAsFile: () => file })),
    types: ['Files'],
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FileDropzone', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('toggles the highlight class on dragEnter / dragLeave', () => {
    render(<FileDropzone onFiles={vi.fn()} />)
    const target = getDropTarget()

    expect(target.className).not.toContain('border-primary')

    fireEvent.dragEnter(target)
    fireEvent.dragOver(target)
    expect(target.className).toContain('border-primary')
    expect(target.className).toContain('bg-primary/5')

    fireEvent.dragLeave(target)
    expect(target.className).not.toContain('border-primary')
  })

  it('keeps the drag counter accurate when the zone is disabled mid-drag', () => {
    const { rerender } = render(<FileDropzone onFiles={vi.fn()} />)
    const target = getDropTarget()

    // User drags over the zone…
    fireEvent.dragEnter(target)
    fireEvent.dragOver(target)
    expect(target.className).toContain('border-primary')

    // …then an upload starts and the zone goes disabled while the cursor is
    // still over it; the highlight is suppressed visually.
    rerender(<FileDropzone onFiles={vi.fn()} disabled />)
    expect(target.className).not.toContain('border-primary')

    // …and the user leaves without dropping. The counter must still decrement.
    fireEvent.dragLeave(target)

    // Upload finishes, zone re-enables, user drags over again.
    rerender(<FileDropzone onFiles={vi.fn()} />)
    fireEvent.dragEnter(target)
    fireEvent.dragOver(target)
    expect(target.className).toContain('border-primary')

    // A single dragLeave clears it — counter was 1, not 2.
    fireEvent.dragLeave(target)
    expect(target.className).not.toContain('border-primary')
  })

  it('emits accepted files on drop', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const pdf = makeFile('report.pdf', 'application/pdf')
    const docx = makeFile(
      'memo.docx',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

    fireEvent.drop(target, { dataTransfer: dataTransferWith([pdf, docx]) })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([pdf, docx])
  })

  it('rejects an oversized file and shows the "too large" error', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const big = makeFile('huge.pdf', 'application/pdf')
    Object.defineProperty(big, 'size', { value: 60e6, configurable: true })

    fireEvent.drop(target, { dataTransfer: dataTransferWith([big]) })

    expect(onFiles).not.toHaveBeenCalled()
    // Surfaced both in the visible list and the sr-only alert region.
    expect(screen.getAllByText(/too large/i).length).toBeGreaterThan(0)
  })

  it('rejects an unsupported file type and shows the "unsupported" error', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const zip = makeFile('archive.zip', 'application/zip')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([zip]) })

    expect(onFiles).not.toHaveBeenCalled()
    expect(screen.getAllByText(/unsupported/i).length).toBeGreaterThan(0)
  })

  it('accepts a .md file whose MIME type is empty (browser quirk)', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const md = makeFile('NOTES.md', '')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([md]) })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([md])
  })

  it('rejects a good-extension file whose MIME is a non-ambiguous mismatch', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    // .md extension passes, but `text/html` is neither allowlisted nor
    // ambiguous (≠ '' / 'application/octet-stream') → strict reject.
    const spoofed = makeFile('note.md', 'text/html')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([spoofed]) })

    expect(onFiles).not.toHaveBeenCalled()
    expect(screen.getAllByText(/note\.md/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/PDF, DOCX, XLSX, CSV, TXT, or Markdown only/i).length).toBeGreaterThan(0)
  })

  it('accepts a good-extension file whose MIME is application/octet-stream (ambiguous)', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const csv = makeFile('data.csv', 'application/octet-stream')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([csv]) })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([csv])
  })

  it('accepts a good-extension file whose MIME is empty', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const csv = makeFile('data.csv', '')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([csv]) })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([csv])
  })

  it('partitions a mixed batch: accepts the good file, lists the bad one', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    const good = makeFile('data.csv', 'text/csv')
    const bad = makeFile('script.exe', 'application/octet-stream')

    fireEvent.drop(target, { dataTransfer: dataTransferWith([good, bad]) })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([good])
    expect(screen.getAllByText(/script\.exe/).length).toBeGreaterThan(0)
  })

  it('opens the OS picker when the button is activated via keyboard', async () => {
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
    const user = userEvent.setup()
    render(<FileDropzone onFiles={vi.fn()} />)

    const target = getDropTarget()
    target.focus()
    await user.keyboard('{Enter}')
    expect(clickSpy).toHaveBeenCalled()

    clickSpy.mockClear()
    await user.keyboard(' ')
    expect(clickSpy).toHaveBeenCalled()
  })

  it('is inert when disabled: drop is a no-op and the button is aria-disabled', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} disabled />)
    const target = getDropTarget()

    expect(target).toHaveAttribute('aria-disabled', 'true')
    expect(target).toBeDisabled()

    const pdf = makeFile('report.pdf', 'application/pdf')
    fireEvent.drop(target, { dataTransfer: dataTransferWith([pdf]) })
    expect(onFiles).not.toHaveBeenCalled()
  })

  it('drops the sub-line in the compact variant', () => {
    const { rerender } = render(<FileDropzone onFiles={vi.fn()} variant="full" />)
    expect(screen.getByText(/up to 50 MB each/i)).toBeInTheDocument()

    rerender(<FileDropzone onFiles={vi.fn()} variant="compact" />)
    expect(screen.queryByText(/up to 50 MB each/i)).not.toBeInTheDocument()
    expect(screen.getByText(/drag more here or click to add/i)).toBeInTheDocument()
  })

  it('clears stale rejections once a valid file is added', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    fireEvent.drop(target, { dataTransfer: dataTransferWith([makeFile('a.zip', 'application/zip')]) })
    expect(screen.getAllByText(/a\.zip/).length).toBeGreaterThan(0)

    fireEvent.drop(target, {
      dataTransfer: dataTransferWith([makeFile('good.pdf', 'application/pdf')]),
    })
    expect(screen.queryByText(/a\.zip/)).not.toBeInTheDocument()
  })

  it('replaces (does not append) the rejection list on repeated all-bad drops', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    fireEvent.drop(target, {
      dataTransfer: dataTransferWith([makeFile('a.zip', 'application/zip'), makeFile('b.exe', 'application/octet-stream')]),
    })
    expect(screen.getAllByText(/a\.zip/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/b\.exe/).length).toBeGreaterThan(0)

    fireEvent.drop(target, {
      dataTransfer: dataTransferWith([makeFile('c.iso', 'application/octet-stream')]),
    })
    // Previous batch's entries are gone — only the current drop's rejection shows.
    expect(screen.queryByText(/a\.zip/)).not.toBeInTheDocument()
    expect(screen.queryByText(/b\.exe/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/c\.iso/).length).toBeGreaterThan(0)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(1)
  })

  it('clears the "files added" announcement after a subsequent all-bad drop', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} />)
    const target = getDropTarget()

    fireEvent.drop(target, { dataTransfer: dataTransferWith([makeFile('ok.pdf', 'application/pdf')]) })
    expect(screen.getByText(/1 file added/i)).toBeInTheDocument()

    fireEvent.drop(target, { dataTransfer: dataTransferWith([makeFile('bad.zip', 'application/zip')]) })
    expect(screen.queryByText(/file added/i)).not.toBeInTheDocument()
  })
})
