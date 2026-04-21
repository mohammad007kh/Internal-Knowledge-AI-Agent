import type { Config } from 'tailwindcss'

/**
 * Tailwind CSS v4 uses CSS-first configuration via `@theme` in `src/app/globals.css`.
 * This file is retained only as a compatibility shim for tools (IDE extensions,
 * the Tailwind CSS IntelliSense plugin) that still expect a JS config.
 *
 * Do NOT add theme tokens here — they will be ignored by the v4 engine.
 * Add theme tokens, colors, and variants to `globals.css` under `@theme`.
 *
 * See: https://tailwindcss.com/docs/upgrade-guide
 */
const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/features/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  plugins: [],
}

export default config
