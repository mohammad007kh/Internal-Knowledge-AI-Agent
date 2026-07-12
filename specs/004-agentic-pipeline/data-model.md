# Data Model — Transparent Multi-Step Agent (004-agentic-pipeline)

**Date**: 2026-06-04 · **Source**: spec.md (Key Entities) + research.md (R1-R10)

Tenancy: single-tenant (registry). All new columns/tables follow registry
conventions (snake_case, UUID PKs, audit columns, soft-delete where rows are
user-visible artifacts, Alembic versioned migrations).

---

## 1. Source Intent (extends `sources` table)

Mirrors the existing AI auto-naming pattern (`name_status` /
`description_status`) — live-with-flag, no approval gate, tri-state used as a
**capability ramp** (clarify session Q1).

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `purpose` | `Text` | yes | null | Admin-authored business purpose (1-2 sentences). AI never writes this field (FR-002: admin supplies purpose). |
| `example_questions` | `JSONB` (list[str]) | yes | null | ~3 sample questions; AI-proposed after study, admin-editable. |
| `out_of_scope` | `JSONB` (list[str]) | yes | null | Topics this source cannot answer; AI-proposed, admin-editable. |
| `cross_source_hints` | `JSONB` (list[{topic, source_id}]) | yes | null | Optional "for X see source Y" redirects. v1: admin-authored only. |
| `intent_status` | `String(16)` | no | `'pending_ai'` | `pending_ai \| ai_set \| user_set` — one status for the intent bundle. |
| `intent_updated_at` | `DateTime(tz)` | yes | null | Stamped on any intent write (AI or admin). |

**Capability ramp (load-bearing rule):**
- `ai_set`: `purpose`(if present)/`example_questions` inform routing +
  grounding; `out_of_scope` is **advisory** — may down-rank a source as a
  tie-breaker among qualified candidates; MUST NOT exclude or hard-decline.
- `user_set` (admin saved a review): `out_of_scope` gains hard-decline
  authority (FR-005).

**State transitions:** `pending_ai → ai_set` (studying/auto-intent task
writes proposals) · `ai_set → user_set` (admin saves review) ·
`user_set → user_set` (admin edits) · re-study NEVER downgrades `user_set`
content (mirror of auto-naming's "never overwrite human values").

**Propose semantics are BUNDLE-level (post-review M5):** there is no
per-field provenance — re-propose runs only while `intent_status !=
'user_set'` and then replaces the AI-writable fields together (matching the
auto-naming row-level precedent). Enforced with a conditional UPDATE
(`… WHERE intent_status != 'user_set'`) inside the proposal task to prevent
a TOCTOU race with a concurrent admin save. The proposal task NEVER writes
`purpose` (admin-only field) and NEVER writes `cross_source_hints`
(admin-only in v1).

**Prompt placement (not schema, but contract):** intent renders ABOVE the
schema block in the pinned context chunk (survives `_MAX_TABLES`
truncation); router/planner prompt gets purpose+examples+out_of_scope
(~150 tokens/source); synthesizer gets purpose+schema. **All THREE existing
consumers of `source.description` get the same precedence treatment**
(post-review m8): the pinned schema chunk, `source_router`'s catalog, and
`text_to_query`'s schema-sketch fallback. **Injection hygiene (security
review F1):** every intent field renders inside unambiguous delimiters
(e.g. `<source_purpose>…</source_purpose>`) and prompts instruct the model
to treat the content as data; values are sanitized at write time (PUT
validation AND proposal-task output validation) against instruction-like
leading patterns; length caps as below.

## 2. Agent State extensions (LangGraph state — not persisted)

| Field | Type | Notes |
|---|---|---|
| `raw_user_intent` | `str` | Original user utterance; never mutated (today `query` is rewritten by query_analyzer). |
| `plan` | `list[PlanStep]` | Pending steps. |
| `past_steps` | `list[StepResult]` | Completed/failed steps with outputs + verification verdicts. |
| `current_step` | `PlanStep \| None` | In-flight step. |
| `plan_revision` | `int` | 0 or 1 (cap enforced at edges). |
| `total_input_tokens` / `total_output_tokens` | `Annotated[int, operator.add]` | EXISTING fields — converted to **additive reducers**; every LLM node returns its usage delta (enumerated set in research.md R2). Synthesizer output is budget-ESTIMATED pre-call, reconciled post-stream. |
| `budget` | `{max_steps, max_retries_per_step, max_revisions, token_ceiling, deadline}` | Read-only config snapshot for guards. |

(No `clarification_pending` state field — clarification is a terminal SSE
event per R5; the reply arrives as the next turn via history. Post-review
correction: a cross-turn pending field would be vestigial.)

**PlanStep** (typed dict): `{id: str, description: str, source_id: UUID,
sub_query: str, depends_on: list[str], status:
pending|active|done|failed, retry_count: int}` — single source per step
(R1). `sub_query` may contain named references (`{{s1.output}}`) that the
executor resolves deterministically before dispatch (R1b).

**StepResult**: `{step_id, output_chunks: list[dict], generated_sql: str|None,
bound_inputs: {refs: dict[str, str], truncated: bool} | None,
verification: {verdict: acceptable|partial|unacceptable, reason: str,
checks: dict}, narration: str}` — `bound_inputs` records exactly what was
interpolated (R1b); the verifier judges the RESOLVED sub_query.
`output_chunks` are step-scoped (the executor sets per-step scratch — one
source_id, step sub_query, that source's schema chunk — and writes results
here, NOT into the turn-wide `retrieved_chunks`; post-review M4).

## 2b. Execution state machine & verification spec (Context-Pinning copy)

_These are the load-bearing R-decisions restated here verbatim so task files
embed them without needing research.md (post-review readiness fix)._

**Verify → retry → replan state machine (R4b — the verify node owns the
conditional edge):**

| Condition | Next |
|---|---|
| `verify == acceptable` | next step (or synthesize when plan empty) |
| `verify == partial` | accept + record verdict; synthesizer prompt branches (no retry burn) |
| `verify == unacceptable` AND `step.retry_count < 1` | **executor**, same step, verifier reason injected, `retry_count += 1` |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision < 1` | **replan** (whole-plan revision, reason carried) |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision == 1` | **synthesize-honest-failure** (diagnostics injected) |

**LLM-calling node set for token accumulation (R2)** — each returns its
usage delta into the additive reducers: planner · source-catalog/routing
call (if retained) · SQL-generation · retrieval_grader (light) ·
retrieval_grader (heavy judge) · clarification detection (when enabled) ·
synthesizer (budget-ESTIMATED pre-call from prompt size + max_tokens,
reconciled post-stream — its usage arrives on the final streamed chunk).
Offline eval judge excluded (not a turn cost).

**Heavy DB verification spec (R3)** — for steps that produced SQL:
1. Deterministic gate (no LLM, reuses `db_safety`/sqlglot): 0 rows when the
   sub_query implies results? row count == the injected LIMIT (100 —
   silent truncation)? every referenced table/column exists in the schema
   sketch? filter/JOIN present when the sub_query implies one?
2. ONE cheap-tier LLM judge call over `{resolved sub_query, generated_sql,
   first ~3 rows}` → "do these rows answer the sub_query? YES/PARTIAL/NO +
   reason" — on the `retrieval_grader` slot.
No self-consistency voting. No confirmatory second query in v1.

**Step-input binding (R1b):** executor deterministically interpolates
`{{sN.output}}` references in `sub_query` before dispatch; list outputs
render comma-joined capped at 50 items (`bound_inputs.truncated=true` on
overflow); the verifier judges the RESOLVED sub_query.

## 3. Activity Record (compact persistence on `chat_messages`)

Full payloads are stream-only (FR-018). Persisted compactly:

| Column | Type | Null | Notes |
|---|---|---|---|
| `activity_summary` | `JSONB` | yes | See shape below. Null for pre-feature + non-agentic messages. |

```jsonc
{
  "step_count": 4,
  "source_count": 2,
  "had_replan": false,
  "had_failure": false,         // any retry or abstain
  "budget_hit": false,
  "turn_tokens": {"input": 9120, "output": 1480},
  "cost_label": "medium",        // small | medium | large (budget fraction)
  "plan": [ {"id": "s1", "label": "Read names from users.csv", "status": "done"}, ... ],
  "superseded_plan": null,       // present when had_replan
  "revision_reason": null,
  "roles": [                      // per-role one-liners for the review-mode accordion
    {"role": "planner",  "line": "read names file, then query CRM"},
    {"role": "executor", "step": "s1", "line": "found 7 names in users.csv"},
    {"role": "verifier", "step": "s2", "line": "rows match the 7 names ✓"}
  ]
}
```

No new table: the record is message-scoped, immutable after the turn, and
queried only with its message — a JSONB column is the lean fit. (Langfuse
retains the full trace for operator-depth inspection.)

## 4. Clarification Request (transient + history echo)

No new table. The request is an SSE event (`clarification` extended with
`options[]`); the user's resolution posts as a normal user `chat_messages`
row (clarify session Q4 pattern). The asked question is recoverable from the
preceding assistant flow; `activity_summary.roles` notes that a
clarification occurred for review mode.

**Options payload (wire contract):** `{question: str, options:
[{id, label, hint?, recommended?}], allow_free_text: true}` — 2-4 options.

## 5. Evaluation Case & Run (file-based, NOT database)

Per R8: JSON-golden files in `backend/evals/` (git-versioned, reviewable).

**Case file shape** (`backend/evals/cases/<source-type>/<case-id>.json`):
```jsonc
{
  "id": "db-workspaces-01",
  "source_type": "database",        // file | web | database | multi
  "question": "How many workspaces does Alice have?",
  "expected_kind": "answer",         // answer | decline (honesty case)
  "golden_answer": "Alice has 3 workspaces.",
  "must_include": ["3"],
  "must_not_fabricate": true,
  "fixtures": {"seed": "evals/fixtures/cctp-mini.sql"}
}
```

**Run output** (`backend/evals/runs/<timestamp>-<pipeline-version>.md` + a
JSON sidecar): per-case pass/fail, honesty axis scored separately, tokens
per case, judge model + prompt version, aggregate vs prior run.

## 6. Configuration (env/config — not database)

| Key | Default | Notes |
|---|---|---|
| `PIPELINE_AGENTIC_ENABLED` | `false` | Rollout flag (R10); sandbox honors it first. |
| `AGENT_MAX_PLAN_STEPS` | `5` | Hard cap (R2). |
| `AGENT_MAX_PLAN_REVISIONS` | `1` | Hard cap. |
| `AGENT_MAX_STEP_RETRIES` | `1` | Hard cap. |
| `AGENT_TOKEN_CEILING_INPUT` / `_OUTPUT` | `30000` / `4000` | Seed values; replaced by p95 from eval runs (R9). |
| `AGENT_TURN_DEADLINE_SECS` | TBD at build | Wall-clock guard. |

## 7. LLM stage slots (seeded rows, not migration)

`STAGES` registry extends with two admin-tunable slots: **`planner`** and
**`retrieval_grader`** (shared by light + heavy verification; R3).
Concrete paths (Context-Pinning fix): defaults live in
`backend/src/agent/stage_defaults.py` (`STAGE_DEFAULTS` dict); idempotent
seeding + link-verification in `backend/src/services/startup_seed.py`
(every slot in `STAGES` must be seeded/linked at startup). Existing 11
slots unchanged; `reflector` remains independent and default-OFF
(Constitution IV).

## 8. Migration plan (Alembic, versioned)

1. `0036_source_intent` — six columns on `sources` (§1), server defaults,
   index on `intent_status`. (Current Alembic head: 0035 — verified;
   `down_revision = '0035'` for 0036, `'0036'` for 0037.)
2. `0037_message_activity` — `activity_summary JSONB` on `chat_messages`,
   plus a DB-level guard for compact persistence (security review F5):
   `CHECK (pg_column_size(activity_summary) <= 16384)` — application code
   additionally caps `roles[].line` at 200 chars and step labels at 200
   chars; `step` SSE `summary` is application-generated narration
   ("first 3 items + count"), never raw row slices.

Both expand-only (no destructive change); existing rows get
`intent_status='pending_ai'` / `activity_summary=NULL` and degrade
gracefully everywhere (UI hides what's absent).

## Validation rules (from requirements)

- `purpose` ≤ ~500 chars; `example_questions` ≤ 5 items; `out_of_scope`
  ≤ 10 items (router token budget protection).
- `intent_status` transitions only along the ramp (no `user_set → ai_set`).
- Plan steps: `source_id` MUST be within the asking user's permitted set at
  planning time AND re-checked at execution (FR-009; FX41 lesson — re-clip
  like `source_router` does).
- `activity_summary.roles[].line` ≤ 200 chars each (compact persistence).
