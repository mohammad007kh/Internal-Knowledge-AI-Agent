# T-008: Citation Panel + Clarification Card + Guardrail Card

**Status**: Not Started
**Created**: 2026-04-21
**User Story**: US-2
**Requirement**: FR-016, FR-017, FR-018
**Priority**: P0
**Feature**: Phase 2 — Product Completion (Internal Knowledge AI Agent)
**Branch**: `003-phase2-completion`
**Platform**: Web (Next.js 15 App Router frontend)

---

## 📋 Embedded Context

### Feature Summary
Phase 2 closes the gap between the current working skeleton and the full product vision. This task layers three specialized response cards on top of the chat streaming surface built in T-007: a collapsible Citation Panel with anchor-linked inline markers, a Clarification Card for when the agent needs more context, and a Guardrail Card for when a prompt is blocked by safety policy. These three components fully implement FR-016 through FR-018 and are the terminal UI surfaces for the corresponding SSE events (`citations`, `clarification_needed`, `guardrail_blocked`).

### Registry Standards (Project Defaults — Locked)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | context + TanStack Query |
| `frontend.data_fetching` | tanstack-query |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `frontend.routing` | next-router (App Router) |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `ui_specs.responsive` | true |
| `ui_specs.accessibility` | wcag-aa |
| `conventions.files` | kebab-case (Next.js components) |
| `conventions.classes` | PascalCase |
| `backend.sse_pattern` | fetch() + ReadableStream (NOT EventSource) |
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer (Authorization: Bearer <token>) |

### Domain Rules (frontend-developer + typescript-pro)
- All API calls go through `apiClient` in `src/lib/api-client.ts` — never use raw `fetch` or axios directly in components
- Define typed API functions in `src/lib/api/` directory
- TanStack Query for ALL server state — never store server data in `useState`
- Use `useQuery` and `useMutation` for all API interactions
- SSE streaming uses `fetch()` with `ReadableStream` — NOT `EventSource`
- Forms use React Hook Form + Zod schema validation
- All new pages use shadcn/ui components
- Accessibility: all interactive elements need proper `aria-label` or visible label
- **No raw HTML injection**: any HTML derived from model output must be safe — prefer replacing citation markers with React elements post-parse, NOT `dangerouslySetInnerHTML`

### API Contracts
```
SSE Events (from POST /api/v1/chat/sessions/{id}/messages — set up in T-007):
  citations             → { items: Citation[] }
  clarification_needed  → { question: string }
  guardrail_blocked     → { message: string }

Citation type:
  {
    index: number,
    source_id: string,
    source_name: string,
    excerpt: string,
    page?: number
  }
```

### Gate Criteria
- TypeScript strict mode compiles without new errors
- Citation panel collapsible, chevron toggles, defaults collapsed
- Inline `[n]` markers in message text are clickable anchors that scroll to the citation
- Clarification card submits back into the same session via existing send handler
- Guardrail card is display-only (no interactive elements)
- Visual distinction: citations neutral, clarification amber/yellow, guardrail red/destructive
- WCAG AA: all icons have `aria-hidden`, cards have `role="region"` with `aria-label`

---

## 🎯 Objective

Build three response-surface components — CitationPanel, ClarificationCard, GuardrailCard — and wire them into the MessageThread rendered by T-007. These components consume the `citations`, `clarification_needed`, and `guardrail_blocked` SSE events respectively. They must be visually distinct, accessible, and integrate cleanly below assistant messages without disrupting the streaming token display.

---

## 🛠️ Implementation Details

### Files to Update

1. **`frontend/src/components/chat/CitationPanel.tsx`** — Complete citation display
   - Props:
     ```typescript
     interface CitationPanelProps {
       citations: Citation[]  // from @/lib/api/chat
     }
     ```
   - Renders below the assistant message
   - Collapsed by default; expand/collapse via chevron toggle (lucide `ChevronDown` rotating)
   - Header row: "Sources (N)" + chevron button; clicking toggles `isExpanded`
   - Body (when expanded): one row per citation:
     - `[n]` number (bold), the source name (medium weight), dash, then excerpt in italic quotes
     - Page indicator `— page X` if `citation.page` is set
     - Each row is anchored with `id={`cite-${citation.index}`}` so inline superscripts can scroll to it
   - Each citation row is itself a link to `/sources/[source_id]` (opens in new tab)
   - Use `Card` / `Collapsible` shadcn components
   - Empty state: if `citations.length === 0`, render nothing (return `null`)

2. **`frontend/src/components/chat/ClarificationCard.tsx`** — Complete clarification interaction
   - Props:
     ```typescript
     interface ClarificationCardProps {
       question: string
       onReply: (answer: string) => void
       disabled?: boolean
     }
     ```
   - Renders as a distinct card with amber/yellow theming:
     - Wrapper: shadcn `Card` with class `border-amber-500 bg-amber-50 dark:bg-amber-950/30`
     - Leading icon: lucide `HelpCircle` in `text-amber-600`
     - Header: "I need more information"
     - Body: the `question` prop rendered as paragraph text
   - Contains a shadcn `<Textarea>` for user's reply (min 2 rows, auto-resizing)
   - "Reply" button (shadcn Button, lucide `CornerDownLeft` icon)
   - On submit (Enter or button click): calls `onReply(answer)` with trimmed value; empty answers rejected (button disabled)
   - `disabled` prop disables inputs while a reply is in-flight
   - Local state for textarea value only; parent handles the actual send (which reuses `useChatStream.send`)

3. **`frontend/src/components/chat/MessageThread.tsx`** (T-007 also updates this file — coordinate)
   - Post-process assistant message text to turn inline `[n]` markers into clickable React anchors:
     ```tsx
     function renderMessageWithCitations(text: string, citations: Citation[]) {
       const parts = text.split(/(\[\d+\])/g)
       return parts.map((part, i) => {
         const match = part.match(/^\[(\d+)\]$/)
         if (!match) return <span key={i}>{part}</span>
         const num = parseInt(match[1], 10)
         const hasCitation = citations.some(c => c.index === num)
         if (!hasCitation) return <span key={i}>{part}</span>
         return (
           <sup key={i}>
             <a
               href={`#cite-${num}`}
               className="text-primary hover:underline mx-0.5"
               aria-label={`Citation ${num}`}
             >
               [{num}]
             </a>
           </sup>
         )
       })
     }
     ```
   - After each assistant message: if `message.citations?.length > 0` render `<CitationPanel citations={message.citations} />`
   - If the current streaming state has `clarificationQuestion`: render `<ClarificationCard question={clarificationQuestion} onReply={handleClarificationReply} />` in place of the streaming cursor
   - If the current streaming state has `guardrailMessage`: render `<GuardrailCard message={guardrailMessage} />` in place of the streaming content
   - `handleClarificationReply(answer)` calls the same `send()` function from `useChatStream` with the answer as the content

### Files to Create

4. **`frontend/src/components/chat/GuardrailCard.tsx`** — Guardrail blocked notice
   - Props:
     ```typescript
     interface GuardrailCardProps {
       message: string
     }
     ```
   - Renders as a red / destructive-styled alert card:
     - Wrapper: shadcn `Alert` with `variant="destructive"` OR a custom `Card` with `border-destructive bg-destructive/10`
     - Leading icon: lucide `ShieldAlert` (or `Lock`) with `aria-hidden="true"` in `text-destructive`
     - Header: "Request blocked"
     - Body: the `message` prop rendered as paragraph text
   - No interactive elements — display only
   - Footer hint (small text, muted): "Contact your administrator if you believe this is an error."
   - Clear visual distinction from normal messages AND from ClarificationCard (amber) — this is red/destructive
   - `role="alert"` so assistive tech announces it

### Code / Logic Requirements

- **No `dangerouslySetInnerHTML`**: citation marker transformation done at the React element level (split string, map to spans/anchors)
- **Anchor targets**: each citation has `id={`cite-${index}`}` and smooth-scroll is achieved via `scroll-behavior: smooth` on the thread container or via `element.scrollIntoView({ behavior: 'smooth' })` on click
- **Collapsible state**: CitationPanel's `isExpanded` is local `useState`, not query state
- **Immutability**: props-driven, no mutation; parent passes fresh arrays
- **Theming**: respect dark mode — use Tailwind dark variants (`dark:bg-*`, `dark:border-*`)
- **File size**: each card component should be under 200 lines

---

## 🔌 Wiring Checklist (Web)

- [ ] `MessageThread.tsx` imports `CitationPanel`, `ClarificationCard`, `GuardrailCard`
- [ ] `MessageThread.tsx` imports `Citation` type from `@/lib/api/chat`
- [ ] `MessageThread.tsx` renders `<CitationPanel>` after any assistant message that has `citations`
- [ ] `MessageThread.tsx` renders `<ClarificationCard>` when `useChatStream` exposes `clarificationQuestion`
- [ ] `MessageThread.tsx` renders `<GuardrailCard>` when `useChatStream` exposes `guardrailMessage`
- [ ] Inline `[n]` markers become clickable anchors pointing to `#cite-n`
- [ ] Clicking a citation anchor smoothly scrolls to the corresponding citation row
- [ ] `ClarificationCard.onReply` is wired to re-use the `send()` function from `useChatStream`
- [ ] `GuardrailCard` has `role="alert"`; `ClarificationCard` has `role="region"` with `aria-label="Clarification needed"`
- [ ] All three cards render correctly in both light and dark modes

---

## ✅ Verification

### Verification Command
```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -c "error TS"
```
**Expected**: 0 new TypeScript errors related to chat components (pre-existing errors don't count as long as the count doesn't increase from new files).

### Manual Verification
1. Ask a question that returns citations → assistant text shows inline `[1]`, `[2]` superscript anchors
2. Citation Panel appears below assistant message, collapsed; click chevron → expands showing source name + excerpt
3. Click `[1]` in message body → page smoothly scrolls to citation 1 in the panel
4. Click a citation row → source detail page opens in new tab
5. Ask an ambiguous question → `clarification_needed` event fires; amber ClarificationCard renders with question + textarea
6. Type a clarification answer + click Reply → new user message sent, streaming resumes in the same session
7. Ask a policy-violating question → `guardrail_blocked` event fires; red GuardrailCard renders with message, no interaction
8. Toggle dark mode → all three cards have correct dark-mode styling with adequate contrast
9. Screen reader test: GuardrailCard announced as alert; ClarificationCard region announced with its label

### Accessibility Checklist
- [ ] Citation anchor links have `aria-label="Citation N"`
- [ ] Citation rows are semantic `<li>` inside `<ol>` or have `role="listitem"`
- [ ] ClarificationCard textarea has visible label or `aria-label="Your reply"`
- [ ] ClarificationCard Reply button has `aria-label="Send reply"`
- [ ] GuardrailCard has `role="alert"` (live announcement)
- [ ] GuardrailCard icon has `aria-hidden="true"` (message text carries the meaning)
- [ ] All color contrast meets WCAG AA (amber-600 on amber-50; destructive tokens pre-verified)
- [ ] Focus outlines visible on all interactive elements (citation anchors, reply button)

---

## 📝 Completion Log

<!-- To be filled during /atomicspec.implement -->

- **Started**:
- **Completed**:
- **Files Changed**:
- **Verification Output**:
- **Notes**:
