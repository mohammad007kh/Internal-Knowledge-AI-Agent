'use client'

import type { ReactNode } from 'react'
import { Fragment } from 'react'

/**
 * MarkdownLite — a dependency-free Markdown renderer for assistant chat messages.
 *
 * Supported syntax:
 *   - Fenced code blocks (```lang\n...\n```) → <pre><code>
 *   - Inline code (`text`)                   → <code>
 *   - Bold (**text**)                         → <strong>
 *   - Italic (*text*)                         → <em>
 *   - Links ([text](url))                     → <a target="_blank" rel="noopener noreferrer">
 *   - Line breaks preserved
 *
 * This is a fallback to avoid adding new dependencies. If the project adopts
 * `react-markdown` + `remark-gfm` in the future, replace usages of this
 * component with the richer renderer.
 *
 * Usage:
 *   <MarkdownLite content={message.content} />
 */

interface MarkdownLiteProps {
  content: string
  className?: string
}

interface CodeBlock {
  kind: 'code'
  language: string
  value: string
}

interface TextBlock {
  kind: 'text'
  value: string
}

type Block = CodeBlock | TextBlock

const FENCE_RE = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g

function splitCodeFences(source: string): Block[] {
  const blocks: Block[] = []
  let lastIndex = 0
  FENCE_RE.lastIndex = 0

  for (;;) {
    const match = FENCE_RE.exec(source)
    if (!match) break

    if (match.index > lastIndex) {
      blocks.push({ kind: 'text', value: source.slice(lastIndex, match.index) })
    }

    blocks.push({
      kind: 'code',
      language: match[1] ?? '',
      value: (match[2] ?? '').replace(/\n$/, ''),
    })

    lastIndex = match.index + match[0].length
  }

  if (lastIndex < source.length) {
    blocks.push({ kind: 'text', value: source.slice(lastIndex) })
  }

  return blocks
}

// Match inline code, bold, italic, and links. Order matters — the regex is
// evaluated greedily left-to-right and the first branch that matches wins.
const INLINE_RE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+]\([^)\n]+\))/

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let remaining = text
  let idx = 0

  while (remaining.length > 0) {
    const match = remaining.match(INLINE_RE)
    if (!match || match.index === undefined) {
      nodes.push(remaining)
      break
    }

    if (match.index > 0) {
      nodes.push(remaining.slice(0, match.index))
    }

    const token = match[0]
    const key = `${keyPrefix}-i${idx++}`

    if (token.startsWith('`')) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
        >
          {token.slice(1, -1)}
        </code>
      )
    } else if (token.startsWith('**')) {
      nodes.push(
        <strong key={key} className="font-semibold">
          {token.slice(2, -2)}
        </strong>
      )
    } else if (token.startsWith('*')) {
      nodes.push(
        <em key={key} className="italic">
          {token.slice(1, -1)}
        </em>
      )
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)]\(([^)]+)\)$/)
      if (linkMatch) {
        const [, label, href] = linkMatch
        nodes.push(
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline underline-offset-2 hover:opacity-80"
          >
            {label}
          </a>
        )
      } else {
        nodes.push(token)
      }
    } else {
      nodes.push(token)
    }

    remaining = remaining.slice(match.index + token.length)
  }

  return nodes
}

function renderTextBlock(value: string, blockKey: string): ReactNode {
  const lines = value.split('\n')
  return (
    <Fragment key={blockKey}>
      {lines.map((line, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: stable order within a block
        <Fragment key={`${blockKey}-l${i}`}>
          {renderInline(line, `${blockKey}-l${i}`)}
          {i < lines.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </Fragment>
  )
}

export function MarkdownLite({ content, className }: MarkdownLiteProps) {
  const blocks = splitCodeFences(content)

  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.kind === 'code') {
          return (
            <pre
              // biome-ignore lint/suspicious/noArrayIndexKey: stable parse order
              key={`b${i}`}
              className="my-2 overflow-x-auto rounded-lg bg-muted p-3 text-xs"
            >
              <code
                className={
                  block.language
                    ? `language-${block.language} font-mono`
                    : 'font-mono'
                }
              >
                {block.value}
              </code>
            </pre>
          )
        }

        return renderTextBlock(block.value, `b${i}`)
      })}
    </div>
  )
}
