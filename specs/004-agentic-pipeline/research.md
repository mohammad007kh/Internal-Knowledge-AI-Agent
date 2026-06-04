# Research — Transparent Multi-Step Agent (Agentic Pipeline)

**Feature**: 004-agentic-pipeline · **Date**: 2026-06-04
**Provenance**: This feature was preceded by an unusually deep research phase:
a multi-week brainstorm (`docs/agent-platform-evolution.md`, uncommitted) with
10+ parallel expert consultations (codebase-grounded + field-literature pairs,
with supervisor reconciliation where experts split), plus a 4-question
clarification session recorded in `spec.md → ## Clarifications`. This document
consolidates those findings in Decision / Rationale / Alternatives form.
All NEEDS CLARIFICATION: none remain (zero markers in spec).

---

## R1. Orchestration pattern

- **Decision**: Plan-and-execute on LangGraph — `planner` node emits a typed
  plan (steps with `depends_on`), an `executor` runs steps sequentially, a
  `replan` node may revise once. State carries `raw_user_intent` (immutable),
  `plan`, `past_steps`, `current_step`. Every question goes through the
  planner (1-step plans for simple questions); single graph, no fast-path.
- **Rationale**: Battle-tested production pattern (LangGraph canonical
  tutorial); avoids an LLM hop per step (vs ReAct); uniform architecture
  keeps one eval baseline and one honesty surface. The pipeline already pays
  one routing LLM call/turn (`source_router`), so an always-on planner is
  roughly cost-neutral.
- **Alternatives considered**: ReAct loop (more LLM hops, costlier);
  ReWOO / LLMCompiler DAGs (premature for 2-5 step workflows); fast-path
  bypass for simple questions (rejected: third graph topology, forked eval
  baselines, a router pre-check that itself needs evaluating).

## R1b. Step-input binding (depends_on resolution) — added post-review

- **Decision**: The **executor deterministically interpolates** prior step
  outputs into a dependent step's `sub_query` before dispatch, via named
  references (`{{s1.output}}`) the planner emits in the template. No extra
  LLM hop. `StepResult` gains a typed `bound_inputs` field recording exactly
  what was substituted, so the binding is traced (Langfuse) and available to
  the verifier (which judges the *resolved* sub_query, not the template).
  Output-to-text coercion: list outputs render as comma-joined values capped
  at 50 items (overflow noted in `bound_inputs.truncated`).
- **Rationale**: Plan-review blocker B1 — the mechanism was unspecified and
  is the core data-flow contract of the feature. Deterministic interpolation
  keeps token accounting clean and failure surfaces small.
- **Alternatives considered**: planner pre-binding (impossible — outputs
  unknown at plan time); an LLM "bind inputs" call per step (extra cost +
  new failure surface; YAGNI).

## R4b. Verify → retry → replan state machine — added post-review

| Condition | Next |
|---|---|
| `verify == acceptable` | next step (or synthesize when plan empty) |
| `verify == partial` | accept + record verdict; synthesizer prompt branches (no retry burn) |
| `verify == unacceptable` AND `step.retry_count < 1` | **executor**, same step, verifier reason injected, `retry_count += 1` |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision < 1` | **replan** (whole-plan revision, reason carried) |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision == 1` | **synthesize-honest-failure** (diagnostics injected) |

The **verify node owns the conditional edge**. Three-level fallback:
retry → replan → honest failure. Both caps live in state and are checked
here AND by the edge-level budget guard (belt + suspenders).

## R2. Hard caps & loop safety

- **Decision**: Max 5 steps/plan, max 1 replan/turn, max 1 retry/step, plus
  a per-turn token ceiling — all enforced as deterministic guards at the
  graph's loop edges. Any limit tripping → graceful stop with an honest
  user-facing message. Prerequisite: nodes must accumulate token usage into
  `AgentState.total_input_tokens / total_output_tokens` (today usage is
  measured per-node and discarded; only Langfuse sees it).
- **Rationale**: Field consensus — agentic releases regret unbounded loops
  more than any other defect; a budget the user can't see is as bad as no
  budget ("never spin forever, always narrate" — owner's hard rules).
- **Alternatives considered**: advisory-only budgets (rejected for v1: no
  guarantee); tiered-by-plan-size budgets (rejected: premature config
  surface).
- **Token-accounting precision (post-review B2):** the accumulation
  prerequisite touches EVERY LLM-calling node's return contract — the
  enumerated set is: planner, source-catalog/routing call (if retained),
  SQL-generation, retrieval_grader (light), retrieval_grader (heavy judge),
  clarification detection (when enabled), synthesizer. (Offline eval judge
  excluded — not a turn cost.) Token fields use an **additive reducer**
  (`Annotated[int, operator.add]`) so nodes return deltas — no
  read-modify-write races. **Synthesizer caveat:** its usage arrives on the
  final streamed chunk, AFTER tokens have streamed to the user — so the
  budget guard treats synthesizer output as **estimated pre-call** (prompt
  size + configured max_tokens) and reconciles actuals post-stream for the
  cost record. SC-004's guarantee is therefore: pre-synthesis spend is
  hard-guarded; the synthesizer call is bounded by its own max_tokens.
- **Guard placement precision (post-review m6):** the guard runs before
  each step dispatch and before replan. A single step may overshoot by at
  most one step's spend (SQL-gen + heavy-judge within a step have no
  intra-step check); this is deliberate and bounded by
  `max_steps × worst-case-step-spend + synthesizer max_tokens`.

## R3. Per-step verification depth

- **Decision**: Option B — light grader on every step; heavy verification
  additionally on database/SQL steps only. Both run inside the `verify`
  node, branching on step type. New `retrieval_grader` cheap-tier LLM stage
  slot (do NOT reuse `clarification_detector`). Heavy DB check = (1) free
  deterministic gate reusing `db_safety`/sqlglot (0 rows, LIMIT-100
  truncation, referenced columns exist, filter present when implied) then
  (2) one LLM-judge call over `{sub_query, generated_sql, first ~3 rows}`.
  `generated_sql` (today trace-only in state) becomes verifier input.
- **Rationale**: Two independent experts converged. Thin vector results are
  self-evident; wrong SQL is silent and authoritative (SOTA text-to-SQL
  ~1-in-4 wrong, ~81% semantic errors a light grader waves through).
  Heavy-everywhere would force schema re-fetches on non-DB steps (~40% of
  the token ceiling) and blanket self-correction measurably lowers accuracy.
- **Alternatives considered**: light-everywhere (misses plausible-but-wrong
  SQL); heavy-everywhere (cost + accuracy regression); self-consistency
  voting (5-21x cost, underperforms selection-based checking).

## R4. Recovery & honesty-on-failure

- **Decision**: On failed verification: retry ONCE with the verifier's
  specific reason injected; on second failure, abstain with reason (lead
  with an honest statement; expandable "what I tried" incl. the failing SQL
  on demand; suggested next actions as quick-reply buttons). A deterministic
  diagnostics injector writes a `<RETRIEVAL_DIAGNOSTICS>` block into the
  synthesizer prompt so "queried X, got 0 rows, because…" is grounded, not
  guessed. Fabrication in this state is prohibited (spec FR-013).
- **Rationale**: "A refusal is a successful fence against a fabrication."
  Blind retries corrupt correct results — retry only with a concrete reason.
- **Alternatives considered**: silent caveat-and-proceed (rejected — trust);
  unlimited retries (rejected — cost + loop risk).

## R5. Clarification mechanism

- **Decision**: Clarify-with-options at the planner boundary only: when the
  planner cannot confidently choose between real alternatives, emit a
  clarification with 2-4 options + free-text escape hatch, BEFORE executing.
  Reuse the platform's existing clarification wire event + frontend
  `ClarificationCard` (extended with an `options[]` payload); the user's
  choice posts as a normal user message. Implementation reuses the existing
  emit-event-and-end-turn pattern (no LangGraph `interrupt()`/checkpointer
  dependency in v1 — the reply arrives as the next turn with history).
- **Rationale**: The bones exist (nodes + card, currently OFF because the
  old trigger fired on everything). Options-not-free-text is the owner's
  priority. Avoiding `interrupt()` avoids introducing a persistent
  checkpointer dependency this phase.
- **Alternatives considered**: always-on clarify (rejected — the documented
  reason it was disabled); mid-flight user-asks (parked — retry-then-explain
  first); LangGraph `interrupt()`+`Command(resume)` (deferred — needs a
  durable checkpointer; the event pattern is equivalent UX with less infra).

## R6. Source intent metadata

- **Decision**: Per-source `purpose`, `example_questions[]`,
  `out_of_scope[]` (+ optional cross-source hints). Hybrid authoring: AI
  proposes after the studying pass; admin authors the purpose. Live
  immediately with the platform's existing tri-state status vocabulary
  (`pending_ai → ai_set → user_set`) as a **capability ramp**: AI-proposed
  content informs selection/grounding at `ai_set`, but out-of-scope gains
  hard-decline authority only at `user_set` (unreviewed out-of-scope may
  only down-rank as a tie-breaker, never exclude or decline). Intent is
  pinned ABOVE the schema render so it survives `_MAX_TABLES` truncation.
  Router prompt gets purpose+examples+out_of_scope (~150 tokens/source);
  synthesizer gets purpose+schema.
- **Rationale**: Mirrors the existing AI auto-naming live-with-flag
  precedent (`auto_name_source.py`); supervisor-reconciled split protects
  trust (no unreviewed AI guess can cause a wrong hard decline) while
  delivering day-one value. Fixes the pre-existing gap that
  `Source.description` never reaches the synthesizer prompt.
- **Alternatives considered**: held-until-approved (rejected — recreates the
  no-intent problem per unreviewed source, contradicts platform norm);
  fully-automatic (rejected — produces the generic descriptions that caused
  the original complaint).

## R7. Streaming & transparency UX

- **Decision**: Two new SSE event types on the existing wire grammar —
  `plan` (full plan payload, once per plan/replan) and `step`
  (`{step_id, label, state: started|finished|failed, summary?}`). Frontend:
  per-turn `activityLog: ActivityEntry[]` array (intermediate, additive
  events — distinct from today's all-terminal event model). Two-layer UX:
  Layer 1 always-visible status line INSIDE the in-flight assistant turn
  (replacing the pulsing dots); Layer 2 collapsed-by-default inline
  accordion with per-role blocks (icons for role identity, color for state
  only), handoffs visible. Plan card (fallback `bg-muted/40` styling) for
  plans ≥2 steps or after revision/clarification; replan = one-line "Plan
  updated — reason" note + old plan collapsed as superseded (NOT a
  strikethrough diff). Post-answer: one-line summary chip in the message
  meta row, compact persistence (`stepCount, sourceCount, hadReplan,
  hadFailure` + per-role one-liners); full payloads stream-only. Deep
  payload inspection reuses the generalized CitationPanel slide-over
  (post-hoc only — NOT for the live tree). Budget-hit = footer banner
  inside the answer bubble + optional "Keep going" quick-reply that starts
  a NEW turn with fresh budget. Cost note = plain-language size leading,
  token count as dimmed suffix, inside the panel only.
- **Rationale**: Frontend SSE parser drops unknown events (backend can ship
  first); designed by two UI/UX experts against Claude/Perplexity/Cursor/
  Devin patterns; the live-tree-in-slide-over assumption was explicitly
  corrected (focus-stealing overlay hostile to live updates).
- **Alternatives considered**: new streaming protocol / Vercel AI SDK
  message-stream adoption (rejected — needless migration); strikethrough
  replan diff (rejected — noisy, ages badly); prominent cost meter
  (rejected — Cursor-credits anxiety backlash).

## R8. Evaluation harness

- **Decision**: Build ALONGSIDE the pipeline work (not after). Outcome-based
  first: frozen Q→A JSON-golden files in `backend/evals/` spanning
  file/web/DB sources, answerable AND unanswerable, with 10-15 dedicated
  honesty cases scored on a separate pass/fail axis. Thin runner invoking
  the pipeline headlessly (`run_pipeline()` already exists), LLM-judge
  (reference-based, binary, different model family than the answerer,
  periodic ~10-20% human spot-check), per-question cost recorded, nightly CI
  job cloned from the `spec_compliance_check.py` job shape. Langfuse scores
  emitted additively (Datasets migration deferred until post-v3 upgrade).
- **Rationale**: MVP ≈2-3 days because the heavy lifting exists; field
  evidence puts post-hoc eval retrofit at 4-6 weeks + blind iteration.
  Outcome evals survive the 1-step→multi-step architecture change
  (trajectory evals deferred until the planner stabilizes — the
  ossification trap).
- **Baseline partitioning (post-review M4/M5):** the baseline run against
  the CURRENT pipeline scores **only the single-source + honesty subsets**
  — that is exactly SC-005's comparison scope. Multi-step (`source_type:
  multi`) cases are AUTHORED in the harness slice but first EXECUTED
  against the agentic pipeline (they measure SC-001 capability, not
  regression). The judge prompt must accept the current pipeline's
  *implicit* declines ("I don't see anything about that…") as a valid
  decline for BASELINE honesty scoring; the agentic pipeline is held to the
  stricter *explained*-decline standard (SC-002).
- **Fixtures provisioning (post-review):** DB-type eval cases need a
  queryable database — the harness includes a fixtures loader that applies
  `fixtures.seed` SQL into an ephemeral schema/database in the existing
  Postgres service and registers a temp source against it (CI compose stack
  already runs Postgres). Fixture data MUST be synthetic-only (see security
  rules in plan.md).
- **Alternatives considered**: build-after (rejected); Langfuse v2 Datasets
  now (rejected — weak comparison UX on pinned version); trajectory/plan
  scoring in v1 (deferred).

## R9. Cost ceiling

- **Decision**: Staged. v1: fixed hard cap (seed 30k input / 4k output
  tokens) checked by a deterministic `budget_guard` at loop edges; graceful
  wrap-up message on hit; ships standalone (never blocked on the eval
  harness). v1.1: replace seed with p95 of measured eval-run cost; quiet
  visibility (admin Langfuse `turn_token_cost`; user plain-language note in
  the panel). Later-maybe: advisory countdown ("~N tokens left" prompt
  injection) with the hard cap underneath. Skipped: tiered budgets.
  "Keep going" = new turn, fresh budget; the cap is never raised mid-turn.
- **Rationale**: Supervisor-reconciled from two expert option sets; the
  measured number must be an upgrade, never a launch dependency.
- **Alternatives considered**: advisory-only (no guarantee), tiered
  (premature), raise-cap-on-click (punches a hole in the hard-cap
  invariant).

## R10. Rollout

- **Decision**: `PIPELINE_AGENTIC_ENABLED`-style operator flag following the
  existing `PIPELINE_V2_ENABLED` precedent. Active first in the admin
  Test/sandbox area only (its SSE consumer is separate, non-persisting, and
  byte-compatible); general users stay on the current pipeline until eval
  gates (SC-002/004/005) pass; flag then widens. The current v2 graph
  remains the rollback path.
- **Rationale**: Nearly free given the existing flag pattern; sandbox is a
  staging ground that already exists; eval gates make "ready" objective.
- **Alternatives considered**: ship-to-everyone (rejected — no staged
  validation), separate staging deployment (rejected — sandbox already is
  one).

## R11. Constitution alignment note

- **Decision**: The new planner-based graph remains THE single pipeline code
  path (Constitution Art. IV): guardrail input/output nodes still wrap every
  request and cannot be bypassed; the reflector stays default-OFF and
  becomes independent of the new `verify`/`replan` mechanism. The
  constitution's descriptive "8-node pipeline" wording refers to the current
  topology; the principles (single path, guardrails always, reflection
  opt-in) are preserved — a constitution text refresh should accompany this
  feature's completion, via the standard amendment process.
- **Rationale**: Keeps Art. IV's intent intact; flags the stale node-count
  wording explicitly rather than silently contradicting it.
