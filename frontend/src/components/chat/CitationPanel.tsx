'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { StepActivityEntry } from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { ExternalLinkIcon, FileTextIcon, XIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { StepStatusBadge } from './StepStatusBadge'
import { ROLE_ICON, ROLE_LABEL } from './agent-roles'
import type { Citation } from './types'

/**
 * The slide-over can present two kinds of detail (T-073b generalization):
 *  - `citation`: a source document excerpt (the original purpose);
 *  - `step`: an agent step's payload from the in-memory activity log.
 *
 * A discriminated union (not an overloaded `citation` prop) keeps each body
 * strongly typed and avoids `'excerpt' in x` probes. The shared chrome (focus,
 * Escape, the open/close transform) is identical for both.
 */
export type PanelContent =
  | { kind: 'citation'; citation: Citation }
  | { kind: 'step'; step: StepActivityEntry }

interface DetailPanelProps {
  content: PanelContent | null
  onClose: () => void
}

/**
 * Right-side slide-over presenting a citation OR an agent step's payload.
 * Open/closed is driven purely by `content !== null`.
 */
export function DetailPanel({ content, onClose }: DetailPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  // Focus close button when opened.
  useEffect(() => {
    if (content) closeRef.current?.focus()
  }, [content])

  // Close on Escape.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && content) onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [content, onClose])

  return (
    <div
      className={cn(
        'fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l border-border bg-background shadow-lg',
        'transition-transform duration-200 motion-reduce:transition-none',
        content ? 'translate-x-0' : 'translate-x-full'
      )}
      role="complementary"
      aria-label={content?.kind === 'step' ? 'Step details' : 'Citation details'}
      aria-hidden={!content}
      // When closed the panel is off-screen via transform but still in the DOM;
      // `inert` removes its close button from the tab order + a11y tree so a
      // keyboard user can't Tab into a hidden control.
      inert={!content}
    >
      {content?.kind === 'citation' && (
        <CitationBody citation={content.citation} closeRef={closeRef} onClose={onClose} />
      )}
      {content?.kind === 'step' && (
        <StepBody step={content.step} closeRef={closeRef} onClose={onClose} />
      )}
    </div>
  )
}

interface PanelChrome {
  closeRef: React.RefObject<HTMLButtonElement | null>
  onClose: () => void
}

function PanelHeader({
  eyebrow,
  title,
  closeLabel,
  closeRef,
  onClose,
}: { eyebrow: string; title: string; closeLabel: string } & PanelChrome) {
  return (
    <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
      <div className="flex min-w-0 flex-col">
        <p className="text-xs text-muted-foreground">{eyebrow}</p>
        <h2 className="truncate text-sm font-medium">{title}</h2>
      </div>
      <Button
        ref={closeRef}
        size="icon"
        variant="ghost"
        className="h-8 w-8 shrink-0"
        onClick={onClose}
        aria-label={closeLabel}
      >
        <XIcon className="h-4 w-4" />
      </Button>
    </div>
  )
}

function CitationBody({ citation, closeRef, onClose }: { citation: Citation } & PanelChrome) {
  return (
    <>
      <PanelHeader
        eyebrow="Source document"
        title={citation.document_title}
        closeLabel="Close citation panel"
        closeRef={closeRef}
        onClose={onClose}
      />
      <ScrollArea className="flex-1 px-4 py-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="gap-1 text-xs">
            <FileTextIcon className="h-3 w-3" />
            {citation.source_name}
          </Badge>
          <Badge variant="secondary" className="text-xs">
            Relevance: {Math.round(citation.score * 100)}%
          </Badge>
        </div>
        <blockquote
          className={cn(
            'rounded-md border-l-4 border-primary/40 bg-muted p-3',
            'text-sm leading-relaxed text-foreground'
          )}
        >
          {citation.excerpt}
        </blockquote>
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
  )
}

function StepBody({ step, closeRef, onClose }: { step: StepActivityEntry } & PanelChrome) {
  const RoleGlyph = ROLE_ICON[step.role]
  return (
    <>
      <PanelHeader
        eyebrow="Agent step"
        title={step.label}
        closeLabel="Close step panel"
        closeRef={closeRef}
        onClose={onClose}
      />
      <ScrollArea className="flex-1 px-4 py-4">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <RoleGlyph className="h-4 w-4 shrink-0" aria-hidden />
            {ROLE_LABEL[step.role]}
          </span>
          <span className="inline-flex items-center gap-1">
            <StepStatusBadge state={step.state} />
          </span>
          {step.progress.total > 0 && (
            <span className="tabular-nums">
              {step.progress.current}/{step.progress.total}
            </span>
          )}
        </div>
        {step.summary ? (
          <p className="rounded-md bg-muted p-3 text-sm leading-relaxed text-foreground">
            {step.summary}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">No additional detail for this step.</p>
        )}
      </ScrollArea>
    </>
  )
}

interface CitationPanelProps {
  citation: Citation | null
  onClose: () => void
}

/**
 * Back-compatible thin wrapper: existing call sites (MessageBubble) and tests
 * still pass a `Citation | null`. Delegates to {@link DetailPanel}.
 */
export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  return (
    <DetailPanel content={citation ? { kind: 'citation', citation } : null} onClose={onClose} />
  )
}
