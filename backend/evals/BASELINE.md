# Eval Baseline — Current Pipeline

**Run date**: 2026-06-06  
**Timestamp**: 20260605T225032Z  
**Pipeline**: `current`  
**Branch**: `004-agentic-pipeline`

---

## Numbers (SC-005 comparison anchor)

| Metric | Value |
|--------|-------|
| Cases executed | 22 |
| Multi cases skipped (R8) | 4 |
| **Single-source pass rate (SC-005 anchor)** | **50.0% (11/22)** |
| Honesty axis — decline cases (implicit-decline acceptance) | 100.0% (11/11) |
| Answer axis | 0.0% (0/11) |
| Bounded termination — SC-004 | PASS — 0 non-terminating |
| Tokens in (aggregate) | 0 ¹ |
| Tokens out (aggregate) | 0 ¹ |
| Judge model | `gpt-4o-mini` ² |
| Judge prompt version | v1 |

¹ Token tracking is not yet wired in the `current` pipeline (state fields exist but
  reducers land in T-050 / Slice C). Both totals are 0 as a result.

² The default judge model is `claude-3-5-sonnet-20241022` (R8: different family from the
  answerer). This baseline run used `gpt-4o-mini` via the `EVAL_JUDGE_MODEL` env-var
  override because the Anthropic SDK is not installed in this environment. The Slice F
  gate run (T-090) should be repeated with a cross-family judge once an Anthropic API
  key is available.

---

## Partition (R8)

The baseline runs ONLY the single-source + honesty subsets per R8. Multi-source cases
(`source_type: multi`) are skipped at baseline — they first execute against the
agentic pipeline (they measure SC-001 capability, not regression).

## Per-subset breakdown

| Source type | Answer pass | Decline pass | Total pass |
|-------------|-------------|--------------|------------|
| database    | 0/4 (0%)    | 6/6 (100%)   | 6/10 (60%) |
| file        | 0/4 (0%)    | 2/2 (100%)   | 2/6 (33%)  |
| web         | 0/3 (0%)    | 3/3 (100%)   | 3/6 (50%)  |
| **Total**   | **0/11 (0%)**| **11/11 (100%)**| **11/22 (50%)** |

## Why answer cases all fail

The `current` pipeline retrieves via pgvector similarity search. The ephemeral
fixtures for database cases provision schema + tables but NO embedding vectors.
The pipeline therefore finds 0 relevant chunks and declines — a FAIL when the
expected answer is a factual response. The agentic pipeline (Slice C) adds
SQL generation (text-to-query) for database sources, which will answer these
cases without needing pre-embedded vectors.

File and web answer cases fail because there are no indexed sources in the eval
environment — the pipeline correctly declines unanswerable queries, but the judge
scores these as FAIL (expected answer, not a decline).

## SC-005 gate (for Slice F)

The agentic pipeline MUST meet or beat **50.0%** on the same 22-case
single-source subset to pass SC-005. The gate is evaluated by `evals.compare`.

---

## T-090 gate run — attempt 2026-06-17 (FAIL; calibration NOT done)

First live agentic gate run. **Result: FAIL** — flag stays sandbox-only; the token
ceiling was **NOT** calibrated (the task contract forbids calibrating on a failed gate).

### What was fixed to even run it
- **Harness P1 (FIXED, code):** `evals/run.py` resolved `container.pipeline()` for the
  agentic run — but that provider wires `sandbox=False`, and the builder only selects the
  plan-and-execute graph when `PIPELINE_AGENTIC_ENABLED AND sandbox AND source_repository`
  (`src/agent/pipeline.py`). So `--pipeline agentic` silently graded **v2-vs-v2**. Now it
  resolves `container.agentic_pipeline()` (sandbox=True) for the agentic run. Verified at
  runtime: the run logs `building agentic (PIPELINE_AGENTIC_ENABLED=True, sandbox=True)`.
- **Harness P2 (mitigated, env):** judge defaults to `claude-3-5-sonnet` (R8 cross-family),
  but the runner wires an OpenAI-only client and no `ANTHROPIC_API_KEY` is set → ran with
  `EVAL_JUDGE_MODEL=gpt-4o` (same family as the gpt-4o-mini answerer; weaker independence).
  Do NOT blank the Langfuse keys to silence tracing: that swaps in `NullLangfuse`, whose
  no-op surface is **missing `.score()`**, crashing `generate` on every case.

### Gate numbers (clean run: baseline 20260617T115104Z-current vs agentic 20260617T115230Z-agentic)
| Pipeline | Answer | Honesty | Total | Termination |
|---|---|---|---|---|
| current (v2) | 0/11 | 11/11 | 11/22 (50.0%) | PASS (0 non-term) |
| agentic | 0/13 | 2/13 | 2/26 | PASS (0 non-term) |

`evals.compare` → **FAIL**: honesty (SC-002) `0.15 < 0.90`; regression (SC-005)
`agentic 0.00 < baseline 0.50`.

### Why it failed — the real blocker for T-090
The FAIL is dominated by an **un-provisioned eval environment**, not certified pipeline
quality:
1. **Answer axis 0% on baseline** is the documented env limitation (no embedded vectors /
   no indexed file·web corpus) — see "Why answer cases all fail" above.
2. **The agentic pipeline did NOT recover the database answer cases via text_to_query**, as
   this doc predicted it would. The planner returns `needs_clarification` instead of planning
   a SQL step (observed on `db-active-users-02`). Almost certainly the ephemeral DB fixture
   provisions schema + tables but **no "studied" schema document**, which the agentic planner
   needs to plan a query → it clarifies instead → no answer.
3. **Agentic honesty regressed (2/13 vs 11/11)**: an unseeded agentic turn produces
   bare/clarifying declines that fail the judge's stricter *explained-decline* bar.

### To certify T-090 (next session, seeded env)
- Provision the agentic prerequisites in the headless fixtures: a studied schema document
  for DB cases (so text_to_query engages) and an indexed corpus for file·web answer cases.
- Optionally provide `ANTHROPIC_API_KEY` + wire an Anthropic judge client for a true
  cross-family judge (P2).
- Re-run baseline + agentic, re-run `evals.compare`; only on PASS calibrate the token
  ceiling to measured p95 and update `core/config.py` + `.env.example`.
