"""Tests for verify_step node and route_after_verify (T-054).

R4b state machine — ALL FIVE routing rows are covered:
  Row 1: acceptable + remaining steps  → "execute_step"
  Row 2: acceptable + empty plan       → "synthesize"
  Row 3: partial (any remaining/empty) → "execute_step" | "synthesize" (not replan/honest_failure)
  Row 4: unacceptable, retry_count=0   → "execute_step", retry_count becomes 1,
                                          reason injected into sub_query prefix
  Row 5a: unacceptable, retry_count=1, plan_revision=0 → "replan"
  Row 5b: unacceptable, retry_count=1, plan_revision=1 → "synthesize_honest_failure"
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.verify import route_after_verify, verify_step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step_result(
    step_id: str,
    verdict: str = "partial",
    reason: str = "",
) -> dict:
    return {
        "step_id": step_id,
        "output_chunks": [{"text": "some data"}],
        "generated_sql": None,
        "bound_inputs": None,
        "verification": {"verdict": verdict, "reason": reason, "checks": {}},
        "narration": "Found some data.",
    }


def _make_plan_step(
    id: str,
    source_id: str = "src-1",
    sub_query: str = "Describe data.",
    retry_count: int = 0,
) -> dict:
    return {
        "id": id,
        "description": f"Description for {id}",
        "source_id": source_id,
        "sub_query": sub_query,
        "depends_on": [],
        "status": "active",
        "retry_count": retry_count,
    }


def _make_state(**overrides) -> dict:
    """Base AgentState with current step s1 and one remaining step s2."""
    current = _make_plan_step("s1")
    base: dict = {
        "trace_id": "trace-test-001",
        "plan": [_make_plan_step("s2")],  # s2 still in plan → s1 not yet done
        "current_step": current,
        "past_steps": [_make_step_result("s1")],  # s1 result already appended by executor
        "plan_revision": 0,
    }
    base.update(overrides)
    return base


def _mock_langfuse() -> MagicMock:
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    span.update.return_value = None
    span.end.return_value = None
    return lf


def _mock_ai_model_resolver(verdict: str, reason: str = "test reason") -> AsyncMock:
    """Return a mock resolver whose LLM always responds with the given verdict."""
    resolver = AsyncMock()
    client = MagicMock()
    client.model_id = "test-model-stub"
    client.temperature = 0.0
    client.max_tokens = 300
    client.custom_prompt = None
    client.http_client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {"verdict": verdict, "reason": reason, "checks": {}}
    )
    response.usage = MagicMock()
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    client.http_client.chat.completions.create = AsyncMock(return_value=response)
    resolver.resolve = AsyncMock(return_value=client)
    return resolver


# ---------------------------------------------------------------------------
# Row 1 — acceptable + remaining steps → "execute_step"
# ---------------------------------------------------------------------------


class TestAcceptableWithRemainingSteps:
    """Row 1: grader says acceptable; plan still has steps after current."""

    @pytest.mark.asyncio
    async def test_route_returns_execute_step(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],  # s2 is next
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable", "looks good"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route == "execute_step"

    @pytest.mark.asyncio
    async def test_verification_verdict_written_as_acceptable(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable", "looks good"),
        )

        state_after = {**state, **delta}
        past = state_after["past_steps"]
        s1_result = next(r for r in past if r["step_id"] == "s1")
        assert s1_result["verification"]["verdict"] == "acceptable"


# ---------------------------------------------------------------------------
# Row 2 — acceptable + empty plan → "synthesize"
# ---------------------------------------------------------------------------


class TestAcceptableEmptyPlan:
    """Row 2: grader says acceptable; no remaining steps in plan."""

    @pytest.mark.asyncio
    async def test_route_returns_synthesize(self):
        state = _make_state(
            plan=[],  # no more steps after current
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable", "all good"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route == "synthesize"

    @pytest.mark.asyncio
    async def test_verdict_written_as_acceptable_in_past_steps(self):
        state = _make_state(
            plan=[],
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable"),
        )

        state_after = {**state, **delta}
        past = state_after["past_steps"]
        s1_result = next(r for r in past if r["step_id"] == "s1")
        assert s1_result["verification"]["verdict"] == "acceptable"


# ---------------------------------------------------------------------------
# Row 3 — partial verdict → accepted, route not replan/honest_failure
# ---------------------------------------------------------------------------


class TestPartialVerdict:
    """Row 3: partial verdict is accepted (not retried); routing is execute_step or synthesize."""

    @pytest.mark.asyncio
    async def test_partial_with_remaining_steps_routes_to_execute_step(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="unacceptable")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("partial", "acceptable but incomplete"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route not in ("replan", "synthesize_honest_failure")
        assert route == "execute_step"

    @pytest.mark.asyncio
    async def test_partial_empty_plan_routes_to_synthesize(self):
        state = _make_state(
            plan=[],
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="unacceptable")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("partial", "partial but ok"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route not in ("replan", "synthesize_honest_failure")
        assert route == "synthesize"

    @pytest.mark.asyncio
    async def test_verdict_written_as_partial_in_past_steps(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1"),
            past_steps=[_make_step_result("s1", verdict="unacceptable")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("partial", "not quite"),
        )

        state_after = {**state, **delta}
        past = state_after["past_steps"]
        s1_result = next(r for r in past if r["step_id"] == "s1")
        assert s1_result["verification"]["verdict"] == "partial"

    @pytest.mark.asyncio
    async def test_partial_does_not_increment_retry_count(self):
        """Partial verdict must NOT retry — retry_count stays 0."""
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=0),
            past_steps=[_make_step_result("s1", verdict="unacceptable")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("partial"),
        )

        state_after = {**state, **delta}
        current = state_after.get("current_step") or state["current_step"]
        assert current["retry_count"] == 0


# ---------------------------------------------------------------------------
# Row 4 — unacceptable, first retry (retry_count=0)
# ---------------------------------------------------------------------------


class TestUnacceptableFirstRetry:
    """Row 4: unacceptable + retry_count=0 → retry same step, count→1, reason injected."""

    @pytest.mark.asyncio
    async def test_route_returns_execute_step(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=0),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "missing key detail"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route == "execute_step"

    @pytest.mark.asyncio
    async def test_retry_count_incremented_to_one(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=0),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "missing key detail"),
        )

        state_after = {**state, **delta}
        current = state_after["current_step"]
        assert current["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_verifier_reason_injected_into_sub_query(self):
        reason = "missing key detail about revenue"
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=0, sub_query="Describe data."),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", reason),
        )

        state_after = {**state, **delta}
        current = state_after["current_step"]
        assert reason in current["sub_query"]

    @pytest.mark.asyncio
    async def test_original_sub_query_still_present_after_prefix(self):
        original_query = "Describe data."
        reason = "output was empty"
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=0, sub_query=original_query),
            past_steps=[_make_step_result("s1", verdict="partial")],
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", reason),
        )

        state_after = {**state, **delta}
        current = state_after["current_step"]
        # The original query must still be in the new sub_query (it's a prefix prepend)
        assert original_query in current["sub_query"]


# ---------------------------------------------------------------------------
# Row 5 — unacceptable, retry exhausted (retry_count == 1)
# ---------------------------------------------------------------------------


class TestUnacceptableExhaustedRetry:
    """Row 5: unacceptable + retry_count=1 → replan or honest_failure based on plan_revision."""

    @pytest.mark.asyncio
    async def test_goes_to_replan_when_plan_revision_zero(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=1),
            past_steps=[_make_step_result("s1", verdict="partial")],
            plan_revision=0,
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "still missing data"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route == "replan"

    @pytest.mark.asyncio
    async def test_goes_to_honest_failure_when_plan_revision_one(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=1),
            past_steps=[_make_step_result("s1", verdict="partial")],
            plan_revision=1,
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "still failing"),
        )

        state_after = {**state, **delta}
        route = route_after_verify(state_after)

        assert route == "synthesize_honest_failure"

    @pytest.mark.asyncio
    async def test_exhausted_does_not_increment_retry_count_further(self):
        """Once retry_count==1, no further increment — node just routes out."""
        state = _make_state(
            plan=[],
            current_step=_make_plan_step("s1", retry_count=1),
            past_steps=[_make_step_result("s1", verdict="partial")],
            plan_revision=0,
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "exhausted"),
        )

        state_after = {**state, **delta}
        current = state_after.get("current_step") or state["current_step"]
        # retry_count must stay at 1 (or the field may be absent if node doesn't touch it)
        assert current["retry_count"] <= 1

    @pytest.mark.asyncio
    async def test_verification_verdict_written_as_unacceptable(self):
        state = _make_state(
            plan=[_make_plan_step("s2")],
            current_step=_make_plan_step("s1", retry_count=1),
            past_steps=[_make_step_result("s1", verdict="partial")],
            plan_revision=0,
        )

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("unacceptable", "truly bad"),
        )

        state_after = {**state, **delta}
        past = state_after["past_steps"]
        s1_result = next(r for r in past if r["step_id"] == "s1")
        assert s1_result["verification"]["verdict"] == "unacceptable"


# ---------------------------------------------------------------------------
# Token delta
# ---------------------------------------------------------------------------


class TestTokenDelta:
    """verify_step must include token counts in its returned state delta."""

    @pytest.mark.asyncio
    async def test_total_input_tokens_present_and_positive(self):
        state = _make_state()

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable"),
        )

        assert "total_input_tokens" in delta
        assert isinstance(delta["total_input_tokens"], int)
        assert delta["total_input_tokens"] > 0

    @pytest.mark.asyncio
    async def test_total_output_tokens_present_and_positive(self):
        state = _make_state()

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable"),
        )

        assert "total_output_tokens" in delta
        assert isinstance(delta["total_output_tokens"], int)
        assert delta["total_output_tokens"] > 0

    @pytest.mark.asyncio
    async def test_token_delta_reflects_mock_usage(self):
        """Confirm the token values match the mock's prompt_tokens=100 + completion_tokens=50."""
        state = _make_state()

        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("partial"),
        )

        # The mock sets prompt_tokens=100 and completion_tokens=50
        assert delta["total_input_tokens"] == 100
        assert delta["total_output_tokens"] == 50


class TestEarlyExits:
    """Verify zero-token early-return paths always honour T-050 token delta contract."""

    @pytest.mark.asyncio
    async def test_no_current_step_returns_zero_token_delta(self):
        state = _make_state(plan=[], current_step=None, past_steps=[])
        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable"),
        )
        assert delta["total_input_tokens"] == 0
        assert delta["total_output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_no_matching_step_id_returns_zero_token_delta(self):
        state = _make_state(
            plan=[],
            current_step=_make_plan_step("s_missing"),
            past_steps=[_make_step_result("s_other")],
        )
        delta = await verify_step(
            state,
            langfuse=_mock_langfuse(),
            ai_model_resolver=_mock_ai_model_resolver("acceptable"),
        )
        assert delta["total_input_tokens"] == 0
        assert delta["total_output_tokens"] == 0
