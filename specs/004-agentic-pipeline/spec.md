# Feature Specification: Transparent Multi-Step Agent (Agentic Pipeline)

**Feature Branch**: `004-agentic-pipeline`
**Created**: 2026-06-04
**Status**: Draft
**Platform**: Web
**Input**: User description: "Evolve the platform from a linear retrieve-then-answer Q&A system into a transparent multi-step agent: sources carry admin-authored purpose/intent metadata; a planner decomposes questions into dependent steps across sources; each step is narrated live and self-verified (light everywhere, heavy for database steps) with honest failure explanations; ambiguity triggers clarify-with-options; a two-layer thinking UX (status line + collapsible per-agent panel) surfaces the agent's work; an outcome-based eval harness and a per-question cost ceiling ship alongside. Source brainstorm: docs/agent-platform-evolution.md"

<!--
  Gate compliance summary (Stations 03-Discovery / 04-PRD / 05-User-Flows):
  - ICP: administrators of self-hosted internal-knowledge deployments and the
    internal end users they serve. Anti-ICP: public-SaaS multi-tenant buyers;
    teams wanting external tool *write* actions through chat (explicitly out
    of scope this phase).
  - Wedge: a self-hosted knowledge assistant whose answers are *transparent
    and honest* — it shows its work, checks its work, and says "I could not
    find this" instead of fabricating.
  - JTBD: "When I ask a question that spans my organisation's files, pages,
    and databases, get me a correct, grounded answer — and when that is not
    possible, tell me why, so I can trust what I read."
  - SaaS rules: single-tenant self-hosted (no billing states); RBAC = existing
    admin/user roles + per-source permissions (the agent must honour them at
    every step); limits = per-question processing ceiling (this spec);
    trial/payment states: not applicable (self-hosted internal tool).
  - Edge-state checklist: covered in Edge Cases below (permission-denied
    sources, limit-hit behaviour, empty/error/loading states, abandoned
    clarifications, session reload mid-answer).
-->

## Clarifications

### Session 2026-06-04

- Q: Is unreviewed AI-proposed source intent live or held? → A: Live
  immediately with an authority split (expert-reconciled): purpose +
  example questions influence selection/answers as soon as proposed
  (flagged AI-proposed); out-of-scope is advisory-only (down-rank, never
  exclude, never hard-decline) until an admin reviews it — decline
  authority requires admin review. Uses the existing
  `pending_ai → ai_set → user_set` status vocabulary as a capability ramp.
- Q: Does every question go through the planner? → A: Yes — uniform
  architecture; a 1-step plan executes with status-line only (plan card UI
  appears only for plans of 2+ steps or when a revision/clarification
  occurs).
- Q: Launch posture? → A: Feature-flagged; the agentic pipeline goes live
  first in the admin Test/sandbox area only, general users stay on the
  current pipeline until evaluation gates pass and the flag is widened.
- Q: "Keep going" after a budget-hit stop? → A: A suggested reply that
  starts a NEW turn with a fresh budget, resuming the unfinished work via
  conversation history. The per-turn cap is never raised mid-turn.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Sources carry their purpose, and answers reflect it (Priority: P1)

An administrator opens a source's settings and records what the source is
*for*: a one-or-two sentence purpose ("Architectural workspaces and buildings
used by the CCTP companion app"), a few example questions it answers well,
and what it can NOT answer. The system proposes a draft of everything it can
infer on its own; the admin only has to supply the business context no system
could guess. From then on, when a user asks a question, the assistant chooses
sources based on their declared purpose and answers with that context in
mind — instead of treating a database as a nameless pile of tables.

**Why this priority**: This fixes a real, user-reported failure (a registered
database produced generic answers because the assistant knew its shape but
not its meaning). It is independently valuable with no other story built,
and every later story depends on this metadata existing.

**Independent Test**: Register a database source, author its intent, ask a
question that the purpose makes answerable in context (e.g. "How many
workspaces does user X have?"), and compare the answer quality with and
without the intent metadata. Also verify a question listed as out-of-scope
produces a redirect/decline rather than a fabricated answer.

**Acceptance Scenarios**:

1. **Given** a database source with no intent metadata, **When** the admin
   opens its settings after the source has been analysed, **Then** a
   system-proposed draft of purpose/example-questions/out-of-scope is shown
   for review and editing.
2. **Given** a source whose intent says "does not contain financial data",
   **When** a user asks that source a financial question, **Then** the answer
   states the source cannot answer it (and points to an alternative source
   if one is hinted) instead of guessing.
3. **Given** two sources with authored intent, **When** a user asks a
   question clearly matching one source's example questions, **Then** that
   source is the one consulted.

---

### User Story 2 - Multi-step questions get planned, dependent answers (Priority: P2)

A user asks a question that no single lookup can answer — e.g. "Find the
users whose names are in the uploaded contact file and tell me how many
workspaces each has in the project database." The assistant works out a
short plan (read the file → extract the names → query the database for those
names → combine), executes the steps in order, and uses each step's result
as input to the next. The user watches it happen: "Got the names: Alice,
Bob, Carlos (+4 more) — querying the project database…"

**Why this priority**: This is the capability leap of the whole feature —
from one-shot lookup to genuine multi-step reasoning across sources. It
requires Story 1's metadata to plan well.

**Independent Test**: Seed a file containing names and a database containing
those users; ask the combined question; verify the final answer contains
per-user results that could only come from chaining the two sources.

**Acceptance Scenarios**:

1. **Given** a file source and a database source, **When** the user asks a
   question requiring data from the file to query the database, **Then** the
   answer reflects both sources chained in the correct order.
2. **Given** a multi-step question, **When** execution is under way, **Then**
   the user sees a live one-line status of the current step at all times,
   including a short partial-result confirmation when a step completes.
3. **Given** any question, **When** a plan is created, **Then** it contains
   at most five steps, and the plan is visible to the user (read-only).

---

### User Story 3 - The assistant checks its own work and is honest when stuck (Priority: P3)

Before trusting any step's result, the assistant reviews it ("did this
actually answer what we needed?"). Database lookups get extra scrutiny,
because a wrong query can return plausible-looking but incorrect rows. When
a check fails, the assistant retries once with a corrected approach; if it
still cannot get a trustworthy result, it stops and explains plainly what it
tried and why it came up short — and suggests what to try next — instead of
fabricating an answer.

**Why this priority**: Honesty-on-failure is the difference between a tool
users trust and one they double-check. It protects against the most
dangerous failure: confidently wrong answers from silently bad lookups.

**Independent Test**: Ask a question whose lookup is guaranteed to return
nothing (e.g. names that don't exist in the database); verify the response
explains what was searched and why nothing matched, offers a next action,
and contains no invented data.

**Acceptance Scenarios**:

1. **Given** a database step that returns zero rows for a question implying
   results, **When** verification runs, **Then** the assistant retries once
   with a revised approach before giving up.
2. **Given** a step that fails verification twice, **When** the answer is
   produced, **Then** it leads with an honest "I couldn't find a reliable
   answer", offers an expandable account of what was tried, and proposes
   next actions as one-click choices.
3. **Given** a successful verification, **When** the user inspects the
   activity detail, **Then** the check's outcome is visible for that step.

---

### User Story 4 - When the question is ambiguous, ask — with choices (Priority: P4)

A user says "the users list", but the platform has two plausible matches
(an HR database and a CRM file). Rather than guessing and doing the wrong
work, the assistant pauses *before executing* and asks which one — showing
2-4 concrete options as buttons, plus a free-text "something else" field.
The chosen option becomes part of the conversation, and the assistant
proceeds. This happens only when genuinely stuck between real alternatives,
never as a routine speed bump.

**Why this priority**: Prevents wasted work and wrong answers on ambiguous
questions; reuses an existing interaction surface; but the agent is useful
without it (it can proceed with best-guess + honesty from Story 3).

**Independent Test**: Create two sources with overlapping subject matter,
ask an ambiguous question, verify the option prompt appears before any
lookup work, and that selecting an option leads to the right source.

**Acceptance Scenarios**:

1. **Given** two sources that both plausibly match the question, **When**
   planning concludes it cannot confidently choose, **Then** the user is
   shown the question with concrete option buttons and a free-text fallback.
2. **Given** the option prompt, **When** the user picks an option, **Then**
   the choice appears in the conversation as the user's reply and execution
   continues with that choice.
3. **Given** an unambiguous question, **When** it is asked, **Then** no
   clarification prompt appears.

---

### User Story 5 - The agent's thinking is visible, on demand (Priority: P5)

While the assistant works, the user always sees a small live status line.
When curious, they can expand a collapsed "agent activity" section attached
to the answer and watch each specialist's reasoning separately — the
planner's plan, the file reader's findings, the database expert's query
check, the answer writer's synthesis — each in its own expandable block,
with handoffs visible. After the answer lands, the activity folds into a
one-line summary ("Used 4 steps · 2 sources · view activity") that reopens
the detail on click — including after the user returns to the conversation
later.

**Why this priority**: This is the trust-and-delight layer ("smart, alive
system"). The pipeline functions without it, but the user experience goal —
watching the agent work like a colleague — depends on it.

**Independent Test**: Ask a multi-step question; verify the status line
updates per step; expand the activity panel mid-run and verify per-agent
blocks populate live; reload the conversation and verify the compact
activity summary is still present and expandable.

**Acceptance Scenarios**:

1. **Given** a question in progress, **When** the user does nothing, **Then**
   a one-line status of the current step is always visible, and the detailed
   thinking stays collapsed by default.
2. **Given** the activity panel expanded during a run, **When** a step
   starts, retries, or completes, **Then** its agent's block reflects the
   change without the user refreshing.
3. **Given** a completed answer with a replan during its run, **When** the
   user reviews it later, **Then** the activity summary marks that something
   needed a retry/replan and the superseded plan is inspectable.

---

### User Story 6 - Operators can measure quality and bound cost (Priority: P6)

An operator maintains a frozen set of test questions (including questions
whose only correct answer is "this cannot be answered from the sources").
Each release of the assistant runs against the set, producing pass/fail
scores and per-question cost, so the operator can prove the new version is
better — not just different. Separately, every live question runs under a
hard processing ceiling: when a question exhausts its budget, the assistant
wraps up gracefully with the best partial answer and says what it didn't
get to — and no question can ever loop or spend without bound.

**Why this priority**: These are the safety nets that make the rest
shippable: quality measured instead of guessed, and a hard guarantee
against runaway cost. Invisible to end users except in the rare limit-hit
moment.

**Independent Test**: Run the evaluation set against the current and new
pipeline and compare reports. Separately, ask a deliberately oversized
question with a low ceiling configured and verify the graceful budget-hit
behaviour.

**Acceptance Scenarios**:

1. **Given** the frozen question set, **When** an evaluation run completes,
   **Then** a report shows per-question pass/fail, the honesty cases scored
   on their own axis, and cost per question, comparable across versions.
2. **Given** a question that reaches its processing ceiling mid-plan,
   **When** the limit trips, **Then** the user receives the best available
   partial answer plus a calm note saying the limit was reached and what
   was not completed — never a silent failure or an error screen.
3. **Given** any question in any state, **When** execution runs, **Then**
   it terminates within the configured step, retry, and budget limits —
   no unbounded loops.

---

### Edge Cases

- **Permission boundaries**: a plan must never include a source the asking
  user cannot access — even if that source would answer the question best.
  If the only viable source is inaccessible, the answer says the question
  cannot be answered with the user's current access (without naming data
  the user is not allowed to see).
- **Ambiguity prompt abandoned**: the user never answers the clarification.
  The conversation simply remains waiting; asking a new question supersedes
  the pending clarification.
- **All steps fail**: verification fails everywhere and the retry budget is
  exhausted → the honest-failure answer (Story 3) is the result; the
  activity record shows what was attempted.
- **Very large database schemas**: when a source's structure is too large to
  consider in full, the source's purpose summary is always preserved in
  what the assistant sees, and the answer notes when relevant detail may
  have been beyond the visible window.
- **Session reload mid-answer**: returning to a conversation that was
  mid-execution shows the answer's final state and the compact activity
  summary; no half-rendered live elements.
- **Unanswerable by design**: questions whose correct outcome is "not in
  the sources" must end in an explained decline (never fabrication) — this
  is a first-class tested behaviour, not an error path.
- **Replan limit**: a plan may be revised at most once per question; if the
  revised plan also fails, the honest-failure path applies.
- **Limit hit mid-step**: budget exhaustion mid-step yields the wrap-up with
  whatever completed steps produced; unfinished steps are named in plain
  language.

## Requirements _(mandatory)_

### Functional Requirements

**Source intent**

- **FR-001**: Administrators MUST be able to record, per source: a purpose
  statement, example questions the source answers well, and topics the
  source cannot answer.
- **FR-002**: After a source is analysed, the system MUST propose a draft of
  the intent metadata it can infer, for the administrator to review and
  edit; the administrator supplies the business purpose. AI-proposed intent
  is live immediately, visibly flagged as AI-proposed and not yet reviewed;
  admin review upgrades its status. The review surface MUST make clear that
  reviewing activates the out-of-scope decline authority (see FR-005).
- **FR-003**: Source selection for a question MUST consider the declared
  purpose, example questions, and out-of-scope topics of each candidate
  source the user can access.
- **FR-004**: Answer composition MUST have access to the source's purpose,
  and the purpose MUST remain available even when a source's structural
  detail is truncated for size.
- **FR-005**: Questions matching a source's declared out-of-scope topics
  MUST NOT be answered from that source as if it were authoritative; the
  response explains the mismatch and follows any cross-source hint.
  Decline authority is tiered by review state: **admin-reviewed**
  out-of-scope topics may produce a hard decline; **unreviewed
  (AI-proposed)** out-of-scope topics are advisory only — they may
  down-rank the source during selection (as a tie-breaker among qualified
  sources, never as exclusion) but MUST NOT cause a hard decline.

**Planning & execution**

- **FR-006**: The system MUST decompose a question into an ordered plan of
  steps, where a step may target one source and may depend on the output of
  earlier steps. Every question goes through planning (uniform
  architecture — no separate fast-path pipeline); simple questions yield a
  1-step plan.
- **FR-007**: Plans MUST be bounded: at most 5 steps, at most 1 plan
  revision per question.
- **FR-008**: The plan MUST be visible to the asking user (read-only),
  including step status as execution progresses; a revised plan MUST be
  announced with its reason, with the superseded plan still inspectable.
  Plan-card visibility is conditional: shown for plans of 2+ steps or when
  a revision or clarification occurred; 1-step plans surface through the
  status line only.
- **FR-009**: Every step MUST honour the asking user's source permissions;
  inaccessible sources are never planned, queried, or named with
  inaccessible detail.

**Verification & honesty**

- **FR-010**: Every step's result MUST be checked for whether it plausibly
  answers the step's goal before it is trusted.
- **FR-011**: Database lookup steps MUST receive additional verification
  capable of catching plausible-but-wrong results (empty results, truncated
  results, structurally suspect queries, results that don't answer the
  question).
- **FR-012**: On a failed check, the system MUST retry the step once with a
  corrected approach informed by the failure reason; on a second failure it
  MUST stop that line of work.
- **FR-013**: When no trustworthy answer is achievable, the response MUST
  lead with an honest statement, offer an expandable account of what was
  tried (including the failing lookup, on demand), and propose next actions
  as one-click choices. Fabricating an answer in this state is prohibited.

**Clarification**

- **FR-014**: When planning cannot confidently choose between real
  alternatives, the system MUST pause before executing and ask the user,
  presenting 2-4 concrete options plus a free-text alternative.
- **FR-015**: Clarification MUST NOT appear for questions the system can
  resolve confidently; a user's option choice becomes part of the
  conversation history.

**Live transparency**

- **FR-016**: While a question is in progress, a one-line status of the
  current activity MUST always be visible, updating at every step start,
  completion (with a short partial-result note), retry, and plan revision.
- **FR-017**: A collapsed-by-default activity panel MUST be available on the
  answer, showing each specialist role's reasoning in its own expandable
  block, populating live, with handoffs between roles visible.
- **FR-018**: After completion, the activity MUST persist as a compact
  summary on the message (steps used, sources used, whether retries
  occurred) that re-expands on demand, surviving conversation reloads.
  Full step payloads need not persist.

**Bounded cost & graceful stop**

- **FR-019**: Every question MUST run under hard limits: maximum steps,
  maximum retries, maximum plan revisions, and a processing-cost ceiling.
  All loops MUST be bounded by at least one of these.
- **FR-020**: Hitting the ceiling MUST produce a graceful wrap-up: the best
  answer from completed work, plus a calm, non-alarming note naming what
  was not completed, attached to the answer and preserved in history. A
  "keep going" suggested reply MAY be offered; choosing it starts a NEW
  question turn with a fresh budget that resumes the unfinished work via
  conversation history — the per-question ceiling is never raised
  mid-question.
- **FR-021**: Per-question processing cost MUST be recorded for operator
  trend review; users see cost only as an unobtrusive plain-language note
  inside the activity panel, never as a prominent meter.

**Quality measurement**

- **FR-022**: The platform MUST maintain a frozen evaluation set of
  questions with expected outcomes, spanning all supported source types and
  including dedicated cases whose correct outcome is an explained decline.
- **FR-023**: An evaluation run MUST score answers pass/fail against
  expected outcomes (honesty cases on a separate axis), record per-question
  cost, and produce a report comparable across pipeline versions.
- **FR-024**: Evaluation MUST be runnable on demand and on a schedule
  without affecting live users.

**Rollout**

- **FR-026**: The agentic pipeline MUST ship behind an operator-controlled
  switch: initially active only in the administrator Test/sandbox area
  while general users continue on the current pipeline; widened to all
  users only after the evaluation gates (SC-002, SC-004, SC-005) pass.

**Out of scope (this feature)**

- **FR-025**: External tool integrations (e.g. third-party services), any
  write actions through chat, mid-execution user prompts beyond the
  pre-execution clarification, and user-editable plans are explicitly out
  of scope for this feature.

### Key Entities

- **Source Intent**: per-source metadata — purpose statement, example
  questions, out-of-scope topics, optional cross-source hints; part
  system-proposed, part admin-authored. Review state follows the
  platform's existing tri-state vocabulary (`pending_ai → ai_set →
  user_set`) used as a capability ramp: AI-proposed (`ai_set`) content is
  live for selection/grounding, but out-of-scope gains hard-decline
  authority only at admin-reviewed (`user_set`).
- **Plan**: an ordered list of steps for one question, with at most one
  revision; carries status and revision reason; superseded plans retained
  for inspection.
- **Plan Step**: a unit of work targeting one source with a goal derived
  from the question and prior step outputs; carries status
  (pending/active/done/failed) and dependency references.
- **Step Result & Verification Outcome**: what a step produced plus the
  check's verdict (acceptable / partial / unacceptable, with reason);
  drives retry/replan/honest-failure behaviour.
- **Activity Record**: the per-question narration tree — per-role blocks,
  status events, plan(s), verification outcomes; persisted compactly with
  the message.
- **Clarification Request**: the question, 2-4 options, optional
  recommendation, and the user's resolution; resolution becomes part of
  conversation history.
- **Evaluation Case & Run**: a frozen question with expected outcome (or
  expected decline) and golden answer; runs produce per-case scores and
  cost, comparable across versions.
- **Question Budget**: the per-question limits (steps, retries, revisions,
  processing ceiling) and the consumed amounts, recorded per answer.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: A question requiring chained data from two sources (file →
  database) is answered correctly end-to-end — a class of question that
  previously could not be answered at all.
- **SC-002**: At least 90% of evaluation honesty cases end in an explained
  decline with zero fabricated data points.
- **SC-003**: Users see the first visible progress signal within 2 seconds
  of asking, and a current-step status is visible at every moment until the
  answer begins.
- **SC-004**: 100% of questions terminate within their configured limits
  across a full evaluation run — zero unbounded loops, zero silent failures.
- **SC-005**: The agentic pipeline's pass rate on the frozen evaluation set
  is at least equal to the previous pipeline's on single-source questions,
  while adding the multi-step capability.
- **SC-006**: An administrator can author a source's intent (review draft +
  write purpose) in under 5 minutes per source.
- **SC-007**: Clarification prompts appear on fewer than 10% of evaluation
  questions (only genuinely ambiguous ones), and in 100% of the
  deliberately-ambiguous test cases.
- **SC-008**: For every multi-step answer, a user can open the activity
  view and see each step's narration and check outcome — including after
  leaving and reopening the conversation.

## Assumptions

- Decisions in `docs/agent-platform-evolution.md` (§7 decisions log) are
  adopted as the product baseline: hybrid intent authoring; plan/narrate/
  verify shipped as one experience; verification depth light-everywhere +
  heavy-for-database-steps; retry once then honest abstention; clarify only
  at the planning boundary; two-layer thinking UX with per-role blocks;
  read-only posture (no external write actions); evaluation built alongside
  (outcome-based first); staged cost ceiling (fixed cap first, measured cap
  later, optional advisory countdown later).
- Initial limit values (step cap 5, single revision, retry once, seed
  processing ceiling) are operator-tunable configuration with sensible
  defaults; the ceiling's long-term value is derived from evaluation-run
  measurements rather than guessed.
- The existing admin/user roles, per-source permission model, and
  conversation experience remain; this feature layers onto them without
  changing authentication or tenancy (single-tenant, self-hosted).
- The evaluation set starts at roughly 20-50 questions and grows toward
  60-100, including 10-15 honesty cases, maintained by the operator.
- The admin Test/sandbox area is an acceptable first home for the new
  transparency UX before general rollout.

## Dependencies

- Source intent (Story 1) is a prerequisite for high-quality planning
  (Story 2) — the planner chooses sources by their declared purpose.
- The evaluation harness (Story 6) should exist before the planning work
  lands, so changes are measured against the current baseline from day one.
- Existing per-source permissions are relied upon as the access-control
  boundary for every planned step.
