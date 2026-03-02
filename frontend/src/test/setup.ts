import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = () => {}

// jsdom does not implement ResizeObserver (used by @radix-ui/react-scroll-area)
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
