import '@testing-library/jest-dom'
import { vi } from 'vitest'

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = () => {}

// jsdom does not implement Element.prototype.hasPointerCapture /
// releasePointerCapture / setPointerCapture. @radix-ui/react-select calls
// these inside its trigger's pointer handlers; without the stubs the trigger
// no-ops on userEvent.click and the SelectContent never mounts, breaking any
// test that opens a shadcn Select. See radix-ui/primitives#1822.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {}
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {}
}

// jsdom does not implement ResizeObserver (used by @radix-ui/react-scroll-area)
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Default mock for next/navigation: components that read the active session
// id from the URL (`SelectedSessionContext`) and call `router.push` need a
// router/params shape during unit tests where there is no real Next.js app
// router. Individual tests can override these via `vi.mocked(...)`.
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({}),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  redirect: vi.fn(),
}))
