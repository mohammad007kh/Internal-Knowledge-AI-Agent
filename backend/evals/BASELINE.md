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
