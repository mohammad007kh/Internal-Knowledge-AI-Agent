import type { AgentRole } from '@/lib/sse/agent-events'
import { Compass, FileText, PenLine, ShieldCheck } from 'lucide-react'
import type { IconGlyph } from './types'

/**
 * Role identity is carried by the ICON, never by colour (colour encodes step
 * STATE only). Shared by the Layer-1 StatusLine and the Layer-2 ActivityAccordion
 * so the 4 wire roles map to glyphs + labels in exactly ONE place.
 */
export const ROLE_ICON: Record<AgentRole, IconGlyph> = {
  planner: Compass,
  executor: FileText,
  verifier: ShieldCheck,
  synthesizer: PenLine,
}

/** Calm, present-tense role labels for the accordion's per-role blocks. */
export const ROLE_LABEL: Record<AgentRole, string> = {
  planner: 'Planning',
  executor: 'Reading sources',
  verifier: 'Verifying',
  synthesizer: 'Writing the answer',
}
