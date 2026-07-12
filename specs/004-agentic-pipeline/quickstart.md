# Quickstart — Transparent Multi-Step Agent (004-agentic-pipeline)

How to run and verify the feature once implemented. (Pre-implementation,
this doubles as the acceptance walkthrough.)

## 1. Enable the feature (sandbox-first rollout)

```bash
# backend/.env
PIPELINE_AGENTIC_ENABLED=true        # default false; sandbox honors it first
docker compose up -d --build backend worker frontend
```

With the flag ON, the admin Test tab uses the agentic pipeline; the general
chat stays on the current pipeline until the flag is widened (FR-026).

## 2. Author source intent (Story 1)

1. `/admin/sources/{id}` → Settings → **Intent** section.
2. After a study completes, an AI-proposed draft appears (status
   `ai_set`, badge "AI-proposed — review to activate declines").
3. Write the one-sentence **purpose**; adjust examples/out-of-scope; Save →
   status `user_set` (out-of-scope now decline-authoritative).

API check: `GET /api/v1/sources/{id}/intent` → `intent_status: "user_set"`.

## 3. Watch a multi-step answer (Stories 2 + 5)

In the Test tab (sandbox), ask the chained question:

> "Find the users whose names are in users.csv and tell me how many
> workspaces each has in the CCTP database."

Expect: live status line per step → plan card (≥2 steps) → per-step
partial-result narration ("Got 7 names…") → answer → activity folds into the
summary chip ("✓ Used 4 steps · 2 sources · view activity"). Expand the
chip: per-role accordion in review mode.

## 4. Verify honesty (Story 3)

Ask for names guaranteed absent from the DB. Expect: one retry (visible as
amber "retrying" state), then an abstain answer leading with "I couldn't
find a reliable answer", expandable "What I tried" (with the SQL behind a
nested toggle), and quick-reply next actions. No fabricated rows.

## 5. Trigger clarification (Story 4)

With two overlapping sources (e.g. two "users" lists), ask the ambiguous
question. Expect: option buttons + free-text card BEFORE any execution;
choosing one posts it as your message and the run proceeds.

## 6. Hit the budget (Story 6, ceiling)

```bash
# Temporarily set a tiny ceiling
AGENT_TOKEN_CEILING_INPUT=2000
```

Ask a multi-step question. Expect: graceful wrap-up footer ("I reached this
question's budget… I didn't get to: …") + "Keep going" quick-reply that
starts a new turn resuming the work.

## 7. Run the eval harness (Story 6, quality)

```bash
cd backend
python -m evals.run --pipeline current     # baseline — scores ONLY the
                                           # single-source + honesty subsets
                                           # (multi cases are skipped; they
                                           # measure capability, not regression)
python -m evals.run --pipeline agentic     # candidate — runs ALL cases
python -m evals.compare runs/<a> runs/<b>  # gate report
```

Partitioning rules (research R8): the baseline never executes
`source_type: multi` cases; the judge accepts the current pipeline's
*implicit* declines ("I don't see anything about that…") as valid declines
for BASELINE honesty scoring, while the agentic pipeline is held to the
stricter *explained*-decline standard.

**Exit-code / threshold contract** (the runner and compare define "done"):
- `evals.run` exits 0 when every case executed and terminated within limits
  (SC-004 check is built into the runner); non-zero on any unbounded/crashed
  case. Results JSON + markdown report written to `evals/runs/`.
- `evals.compare` exits 0 when ALL gates pass: honesty ≥ 90%
  explained-decline on the agentic run (SC-002), agentic pass-rate ≥
  baseline pass-rate on the single-source subset (SC-005); exits 1 with the
  failing gate named in stdout otherwise. CI consumes the exit code.

Nightly CI job runs the same and uploads the report artifact (job modeled on
the repo-root `scripts/spec_compliance_check.py` job in ci.yml — note the
script lives at the REPO ROOT, not under backend/).

## 8. Operator observability

- Langfuse: per-node spans incl. planner/verifier; `turn_token_cost` score
  per turn for trend review.
- Eval reports: `backend/evals/runs/` (git-ignored artifacts, CI-uploaded).
