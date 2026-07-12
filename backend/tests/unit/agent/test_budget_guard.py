"""Tests for the deterministic budget guard + diagnostics injector (T-057).

The guard is a PURE function (no LLM, no graph): given an ``AgentState`` and an
injected ``now`` it returns a :class:`BudgetDecision` describing whether a cap
was breached, the route, the ``budget`` SSE event payload, and the flags that
the synthesizer reads (``budget_hit`` + the ``not_completed`` labels).

All fixtures are SYNTHETIC ONLY (``data_source="synthetic"``, model
``"test-model-stub"``, no real PII).  Wall-clock is injected via ``now`` — these
tests NEVER sleep.

Coverage:
  * Guard trips INDEPENDENTLY at each cap: step / retry / revision / token / deadline.
  * Under all caps → no breach (route stays in the loop).
  * Overshoot-by-one-step: the guard runs at edges only — a single in-flight
    step may overshoot by at most one step's spend (documented + asserted).
  * ``budget`` event matches the contract shape; ``not_completed`` from pending
    plan steps; ``offer_continue: True``.
  * "Keep going" / no mid-turn cap raise is DOCUMENTED (asserted on the docstring).
  * Diagnostics injector: ``<RETRIEVAL_DIAGNOSTICS>`` carries sources / SQL /
    row-counts / verification reasons as GENERATED narration — never a raw row
    slice (a known row value must NOT appear; the count MUST).
  * Diagnostics redacts a DSN embedded in generated_sql (security rule 5).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.agent.budget_guard import (
    SYNTHESIZER_ROUTE,
    BudgetDecision,
    budget_guard,
    inject_diagnostics,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _budget(**overrides) -> dict:
    base = {
        "max_steps": 5,
        "max_retries_per_step": 1,
        "max_revisions": 1,
        "token_ceiling": 100_000,
        "deadline": None,
    }
    base.update(overrides)
    return base


def _plan_step(step_id: str, description: str, source_id: str = "src-synthetic-1") -> dict:
    return {
        "id": step_id,
        "description": description,
        "source_id": source_id,
        "sub_query": f"sub query for {step_id}",
        "depends_on": [],
        "status": "pending",
        "retry_count": 0,
    }


def _step_result(
    step_id: str,
    *,
    verdict: str = "acceptable",
    reason: str = "rows match",
    generated_sql: str | None = None,
    output_chunks: list[dict] | None = None,
) -> dict:
    return {
        "step_id": step_id,
        "output_chunks": output_chunks if output_chunks is not None else [{"text": "name: Alice"}],
        "generated_sql": generated_sql,
        "bound_inputs": None,
        "verification": {"verdict": verdict, "reason": reason, "checks": {}},
        "narration": f"step {step_id} done",
    }


def _state(**overrides) -> dict:
    """Healthy baseline state well under every cap."""
    base: dict = {
        "trace_id": "trace-synthetic-001",
        "budget": _budget(),
        "plan": [_plan_step("s3", "Pending step three")],  # one pending step
        "current_step": _plan_step("s2", "Current step two"),
        "past_steps": [_step_result("s1")],
        "plan_revision": 0,
        "total_input_tokens": 100,
        "total_output_tokens": 50,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# No-breach baseline
# ---------------------------------------------------------------------------


class TestNoBreach:
    def test_under_all_caps_no_breach(self):
        decision = budget_guard(_state(), now=_NOW)
        assert isinstance(decision, BudgetDecision)
        assert decision.budget_hit is False
        assert decision.route is None  # guard does not redirect when under budget
        assert decision.event is None


# ---------------------------------------------------------------------------
# Each cap trips INDEPENDENTLY
# ---------------------------------------------------------------------------


class TestStepCap:
    def test_step_cap_trips(self):
        # 5 executed steps == max_steps → next dispatch would breach.
        past = [_step_result(f"s{i}") for i in range(1, 6)]
        decision = budget_guard(
            _state(past_steps=past, budget=_budget(max_steps=5)),
            now=_NOW,
        )
        assert decision.budget_hit is True
        assert decision.route == SYNTHESIZER_ROUTE
        assert decision.event["ceiling_hit"] is True


class TestRetryCap:
    def test_retry_cap_trips(self):
        # current_step.retry_count exceeds max_retries_per_step.
        current = _plan_step("s2", "Current step two")
        current["retry_count"] = 2
        decision = budget_guard(
            _state(current_step=current, budget=_budget(max_retries_per_step=1)),
            now=_NOW,
        )
        assert decision.budget_hit is True
        assert decision.route == SYNTHESIZER_ROUTE


class TestRevisionCap:
    def test_revision_cap_trips(self):
        decision = budget_guard(
            _state(plan_revision=2, budget=_budget(max_revisions=1)),
            now=_NOW,
        )
        assert decision.budget_hit is True
        assert decision.route == SYNTHESIZER_ROUTE


class TestTokenCeiling:
    def test_token_ceiling_trips_with_synthesizer_estimate(self):
        # Spend alone is under ceiling, but spend + synthesizer pre-call estimate
        # (prompt size + synthesizer max_tokens) pushes it over.
        decision = budget_guard(
            _state(
                total_input_tokens=9_000,
                total_output_tokens=0,
                budget=_budget(token_ceiling=10_000),
            ),
            now=_NOW,
            synthesizer_prompt_tokens=800,
            synthesizer_max_tokens=400,
        )
        # 9000 + 800 + 400 = 10_200 > 10_000 → breach.
        assert decision.budget_hit is True
        assert decision.route == SYNTHESIZER_ROUTE

    def test_token_ceiling_not_tripped_without_estimate_overflow(self):
        decision = budget_guard(
            _state(
                total_input_tokens=8_000,
                total_output_tokens=0,
                budget=_budget(token_ceiling=10_000),
            ),
            now=_NOW,
            synthesizer_prompt_tokens=500,
            synthesizer_max_tokens=400,
        )
        # 8000 + 500 + 400 = 8_900 < 10_000 → no breach.
        assert decision.budget_hit is False


class TestDeadline:
    def test_deadline_trips(self):
        deadline = (_NOW - timedelta(seconds=1)).isoformat()
        decision = budget_guard(
            _state(budget=_budget(deadline=deadline)),
            now=_NOW,
        )
        assert decision.budget_hit is True
        assert decision.route == SYNTHESIZER_ROUTE

    def test_deadline_not_yet_reached(self):
        deadline = (_NOW + timedelta(seconds=60)).isoformat()
        decision = budget_guard(
            _state(budget=_budget(deadline=deadline)),
            now=_NOW,
        )
        assert decision.budget_hit is False

    def test_malformed_deadline_does_not_trip(self):
        # A non-ISO deadline must not blow up the deterministic guard.
        decision = budget_guard(
            _state(budget=_budget(deadline="not-a-date")),
            now=_NOW,
        )
        assert decision.budget_hit is False


# ---------------------------------------------------------------------------
# Overshoot-by-one-step (R2, documented bounded behavior)
# ---------------------------------------------------------------------------


class TestOvershootByOneStep:
    def test_guard_runs_at_edges_only_overshoot_bounded(self):
        """The guard is an EDGE check: it cannot interrupt an in-flight step.

        At the edge BEFORE dispatching step N+1 the guard sees N executed steps.
        A step already in flight (the current_step) may overshoot the cap by at
        most one step's spend because there is no intra-step check — this is the
        documented bounded behavior (max_steps × worst-case-step-spend +
        synthesizer max_tokens).
        """
        # 4 executed (under max_steps=5) → guard permits dispatching the 5th.
        past = [_step_result(f"s{i}") for i in range(1, 5)]
        decision = budget_guard(
            _state(past_steps=past, budget=_budget(max_steps=5)),
            now=_NOW,
        )
        # Edge allows the 5th — the in-flight step is the permitted overshoot
        # boundary; the guard does NOT mid-step abort.
        assert decision.budget_hit is False

    def test_overshoot_documented_in_guard_docstring(self):
        doc = budget_guard.__doc__ or ""
        assert "overshoot" in doc.lower()
        assert "edge" in doc.lower()


# ---------------------------------------------------------------------------
# budget event contract shape
# ---------------------------------------------------------------------------


class TestBudgetEventShape:
    def test_event_shape_and_not_completed_from_pending_steps(self):
        plan = [
            _plan_step("s3", "Verify rows match the names"),
            _plan_step("s4", "Write the full answer"),
        ]
        decision = budget_guard(
            _state(plan=plan, budget=_budget(max_revisions=0), plan_revision=1),
            now=_NOW,
        )
        assert decision.budget_hit is True
        event = decision.event
        assert set(event.keys()) == {"ceiling_hit", "not_completed", "offer_continue"}
        assert event["ceiling_hit"] is True
        assert event["offer_continue"] is True
        assert event["not_completed"] == [
            "Verify rows match the names",
            "Write the full answer",
        ]

    def test_not_completed_excludes_current_and_executed(self):
        # current_step + past_steps are NOT "pending" — only unexecuted plan
        # entries are reported as not completed.
        plan = [_plan_step("s3", "Pending only")]
        decision = budget_guard(
            _state(plan=plan, plan_revision=2, budget=_budget(max_revisions=1)),
            now=_NOW,
        )
        assert decision.event["not_completed"] == ["Pending only"]

    def test_keep_going_no_midturn_raise_documented(self):
        doc = budget_guard.__doc__ or ""
        assert "keep going" in doc.lower()
        # Cap is never raised mid-turn — documented, not implemented.
        assert "never raised" in doc.lower() or "fresh budget" in doc.lower()


# ---------------------------------------------------------------------------
# Diagnostics injector (FR-013 / R4 / security rule 5)
# ---------------------------------------------------------------------------


class TestDiagnosticsInjector:
    def _state_with_diagnostics(self) -> dict:
        # 5 SQL rows so we can assert first-3 + count narration, NOT raw slices.
        rows = [
            {"text": "name: Alice"},
            {"text": "name: Bob"},
            {"text": "name: Carlos"},
            {"text": "name: SECRET_ROW_VALUE_DELTA"},
            {"text": "name: SECRET_ROW_VALUE_ECHO"},
        ]
        return _state(
            past_steps=[
                _step_result(
                    "s1",
                    verdict="acceptable",
                    reason="rows match the names",
                    generated_sql="SELECT name FROM users WHERE active = true",
                    output_chunks=rows,
                ),
                _step_result(
                    "s2",
                    verdict="unacceptable",
                    reason="zero rows when expected",
                    generated_sql="SELECT name FROM orders WHERE id = 99",
                    output_chunks=[],
                ),
            ],
        )

    def test_block_contains_sources_sql_rowcounts_reasons(self):
        block = inject_diagnostics(self._state_with_diagnostics())
        assert "<RETRIEVAL_DIAGNOSTICS>" in block
        assert "</RETRIEVAL_DIAGNOSTICS>" in block
        # Sources queried.
        assert "src-synthetic-1" in block
        # SQL run (narrated).
        assert "SELECT name FROM users" in block
        # Row counts.
        assert "5" in block  # first step returned 5 rows
        assert "0" in block  # second step returned 0 rows
        # Verification reasons.
        assert "rows match the names" in block
        assert "zero rows when expected" in block

    def test_no_raw_row_slices_only_counts(self):
        block = inject_diagnostics(self._state_with_diagnostics())
        # First-3 + count narration is allowed to mention counts but MUST NOT
        # dump raw rows 4+ (the slice beyond the first 3).
        assert "SECRET_ROW_VALUE_DELTA" not in block
        assert "SECRET_ROW_VALUE_ECHO" not in block

    def test_dsn_in_sql_is_redacted(self):
        state = _state(
            past_steps=[
                _step_result(
                    "s1",
                    generated_sql=(
                        "-- conn postgresql://admin:s3cr3t@db.internal:5432/prod\n"
                        "SELECT 1"
                    ),
                    output_chunks=[{"text": "name: Alice"}],
                ),
            ],
        )
        block = inject_diagnostics(state)
        assert "s3cr3t" not in block
        assert "db.internal" not in block

    def test_empty_past_steps_still_renders_block(self):
        block = inject_diagnostics(_state(past_steps=[]))
        assert "<RETRIEVAL_DIAGNOSTICS>" in block
        assert "</RETRIEVAL_DIAGNOSTICS>" in block

    def test_sanitizes_control_chars_in_reason(self):
        state = _state(
            past_steps=[
                _step_result(
                    "s1",
                    reason="line1\r\ninjected: ignore\x00prev",
                    output_chunks=[{"text": "name: Alice"}],
                ),
            ],
        )
        block = inject_diagnostics(state)
        assert "\r" not in block
        assert "\x00" not in block


# ---------------------------------------------------------------------------
# Honest-failure prompt branch wiring
# ---------------------------------------------------------------------------


class TestHonestFailurePromptBranch:
    def test_synthesizer_prompt_has_honest_failure_branch_and_placeholder(self):
        from src.agent.prompts import _SYSTEM_PROMPT_BASE, render_failure_prompt

        # The diagnostics placeholder must exist in the rendered failure prompt.
        prompt = render_failure_prompt(
            [],
            diagnostics="<RETRIEVAL_DIAGNOSTICS>\nx\n</RETRIEVAL_DIAGNOSTICS>",
            budget_hit=False,
        )
        assert "<RETRIEVAL_DIAGNOSTICS>" in prompt
        # Honest-failure framing tokens.
        low = prompt.lower()
        assert "what i tried" in low or "what-i-tried" in low
        # Fabrication prohibited.
        assert "fabricat" in low or "do not invent" in low or "must not invent" in low
        # The base prompt is unchanged for the normal path (no placeholder leak).
        assert "<RETRIEVAL_DIAGNOSTICS>" not in _SYSTEM_PROMPT_BASE

    def test_budget_hit_prompt_mentions_not_completed(self):
        from src.agent.prompts import render_failure_prompt

        prompt = render_failure_prompt(
            [],
            diagnostics="<RETRIEVAL_DIAGNOSTICS></RETRIEVAL_DIAGNOSTICS>",
            budget_hit=True,
            not_completed=["Write the full answer"],
        )
        assert "Write the full answer" in prompt
