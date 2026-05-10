'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { ExternalLinkIcon, FileTextIcon, XIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { Citation } from './types'

interface CitationPanelProps {
  citation: Citation | null
  onClose: () => void
}

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  // Focus close button when opened
  useEffect(() => {
    if (citation) closeRef.current?.focus()
  }, [citation])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && citation) onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [citation, onClose])

  return (
    <div
      className={cn(
        'fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l border-border bg-background shadow-lg',
        'transition-transform duration-200',
        citation ? 'translate-x-0' : 'translate-x-full'
      )}
      role="complementary"
      aria-label="Citation details"
      aria-hidden={!citation}
    >
      {citation && (
        <>
          {/* Header */}
          <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
            <div className="flex min-w-0 flex-col">
              <p className="text-xs text-muted-foreground">Source document</p>
              <h2 className="truncate text-sm font-medium">{citation.document_title}</h2>
            </div>
            <Button
              ref={closeRef}
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0"
              onClick={onClose}
              aria-label="Close citation panel"
            >
              <XIcon className="h-4 w-4" />
            </Button>
          </div>

          {/* Body */}
          <ScrollArea className="flex-1 px-4 py-4">
            {/* Meta */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="gap-1 text-xs">
                <FileTextIcon className="h-3 w-3" />
                {citation.source_name}
              </Badge>
              <Badge variant="secondary" className="text-xs">
                Relevance: {Math.round(citation.score * 100)}%
              </Badge>
            </div>

            {/* Excerpt */}
            <blockquote
              className={cn(
                'rounded-md border-l-4 border-primary/40 bg-muted p-3',
                'text-sm leading-relaxed text-foreground'
              )}
            >
              {citation.excerpt}
            </blockquote>

            {/* External link */}
            {citation.url && (
              <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  'mt-4 inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4',
                  'hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                )}
              >
                <ExternalLinkIcon className="h-3.5 w-3.5" />
                View original document
              </a>
            )}
          </ScrollArea>
        </>
      )}
    </div>
  )
}
