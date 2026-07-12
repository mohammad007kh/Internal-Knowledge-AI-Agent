# SSE Wire Contract — Agentic events (004-agentic-pipeline)

Extends the existing chat SSE grammar (`backend/src/schemas/chat.py`
`StreamEventType`; wire format `event: <type>\n` + `data: <json>\n\n`).
The grammar MUST remain byte-identical across the live chat endpoint and the
admin sandbox endpoint (existing invariant). Frontend parsers drop unknown
event types silently — backend may ship these events before any UI renders
them.

## Event ordering (one agentic turn)

```
session_created?           (existing, lazy-create only)
plan                       (after planner; once — or twice if a revision occurs)
step*                      (started/finished/failed per plan step, incl. retries)
clarification?             (extended payload; TERMINAL for this turn — reply arrives as next turn)
replan?                    (at most once; followed by a fresh `plan` event)
delta*                     (existing; answer tokens)
citations?                 (existing)
budget?                    (emitted once if the ceiling tripped, before/with final delta batch)
title?                     (existing)
done                       (existing; now carries activity_summary)
error                      (existing; unchanged)
```

`plan`, `step`, `replan`, `budget` are **intermediate** events — additive to
the per-turn `activityLog`, never terminal. (Today every non-delta event is
terminal; this is the new event class the frontend state model must support.)

## New event: `plan`

```jsonc
event: plan
data: {
  "revision": 0,                       // 0 = initial, 1 = revised
  "reason": null,                      // present when revision == 1
  "steps": [
    {
      "id": "s1",
      "label": "Read names from users.csv",   // user-facing, plain language
      "source_id": "…uuid…",
      "source_name": "users.csv",
      "depends_on": []
    }
  ]
}
```

UI rule (from spec FR-008): plan card renders only when `steps.length >= 2`
or `revision >= 1` or a clarification occurred; 1-step plans surface via the
status line only.

## New event: `step`

```jsonc
event: step
data: {
  "step_id": "s1",
  "role": "executor",                  // planner|executor|verifier|synthesizer (drives per-role blocks)
  "state": "started",                  // started | finished | failed | retrying
  "label": "Reading users.csv…",       // present-tense for started, past for finished
  "summary": null,                     // short partial result on finished: "Got 7 names: Alice, Bob, Carlos (+4)"
  "progress": {"current": 1, "total": 4}
}
```

Emitted on EVERY step start AND finish/fail/retry (the always-narrate rule).
`summary` carries the verification-aware partial-result note; ≤ 200 chars.

## New event: `replan`

```jsonc
event: replan
data: {
  "reason": "CRM returned emails; switching to email match",
  "superseded_revision": 0
}
```

Always followed by a fresh `plan` event with `revision: 1`. UI renders the
one-line "Plan updated — reason" note and collapses the superseded plan.

## New event: `budget`

```jsonc
event: budget
data: {
  "ceiling_hit": true,
  "not_completed": ["Verify rows match the names", "Write the full answer"],
  "offer_continue": true               // UI may render the "Keep going" quick-reply
}
```

"Keep going" sends an ordinary user message (new turn, fresh budget) — no
special endpoint.

## Extended event: `clarification`

Existing event gains an optional structured payload (absent = legacy
free-text behavior):

```jsonc
event: clarification
data: {
  "question": "Which users did you mean?",
  "options": [
    {"id": "hr", "label": "Employees", "hint": "HR database", "recommended": false},
    {"id": "crm", "label": "Customers", "hint": "CRM file", "recommended": true},
    {"id": "both", "label": "Both"}
  ],
  "allow_free_text": true
}
```

2-4 options; selection posts as a normal user message whose text is the
option label. Terminal for the turn.

## Extended event: `done`

Existing `done` payload gains `activity_summary` (the compact persistence
shape from data-model.md §3) so the frontend can render the post-answer
summary chip without a refetch.

## Compatibility rules

1. No existing event's shape changes in a breaking way (additive fields only).
2. Both SSE consumers (`use-chat-stream.ts`, `useSandboxStream.ts`) must
   handle the new events identically; sandbox ships first (rollout flag).
   Recommended: extract the duplicated event-switch into one shared module.
3. Unknown-event tolerance remains mandatory in all parsers.
4. Langfuse spans remain the operator-depth record; SSE carries only what
   the UI renders (no raw SQL/rows in `step` events — those are slide-over
   fetches scoped by the user's own permissions).

## Security invariants (enforced server-side before emission)

- **`plan` event**: server MUST assert every `steps[].source_id` is within
  the requesting user's permitted source set before emitting (guards
  against planner hallucination leaking source names). Violations → replan
  or honest-failure path, never emission.
- **`clarification` options**: generated exclusively from the permitted
  source set; an option may never name an inaccessible source.
- **`step.summary`**: application-generated narration ("first 3 items +
  count"), ≤200 chars, never a raw slice of result rows.
- **`done.activity_summary`**: compact shape only (see data-model §3);
  size-guarded; scoped to the asking user's own message/session (and
  persisted with that message per FR-018).
