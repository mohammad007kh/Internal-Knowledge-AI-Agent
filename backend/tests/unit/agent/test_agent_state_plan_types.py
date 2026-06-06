"""Unit tests for T-051: PlanStep, StepResult, and AgentState plan fields."""
from __future__ import annotations

from typing import get_type_hints

from src.agent.state import AgentState, PlanStep, StepResult


class TestPlanStepShape:
    def test_planstep_has_required_fields(self) -> None:
        hints = get_type_hints(PlanStep, include_extras=True)
        expected = {"id", "description", "source_id", "sub_query", "depends_on", "status", "retry_count"}
        assert expected == set(hints.keys())

    def test_planstep_valid_dict(self) -> None:
        step: PlanStep = {
            "id": "s1",
            "description": "Retrieve sales data",
            "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "sub_query": "Total sales last month?",
            "depends_on": [],
            "status": "pending",
            "retry_count": 0,
        }
        assert step["id"] == "s1"
        assert step["status"] == "pending"

    def test_planstep_all_status_literals(self) -> None:
        for status in ("pending", "active", "done", "failed"):
            step: PlanStep = {
                "id": "s1",
                "description": "x",
                "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "sub_query": "x",
                "depends_on": ["s0"],
                "status": status,  # type: ignore[typeddict-item]
                "retry_count": 1,
            }
            assert step["status"] == status

    def test_planstep_depends_on_is_list(self) -> None:
        step: PlanStep = {
            "id": "s2",
            "description": "step 2",
            "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "sub_query": "{{s1.output}} summarize",
            "depends_on": ["s1"],
            "status": "pending",
            "retry_count": 0,
        }
        assert step["depends_on"] == ["s1"]


class TestStepResultShape:
    def test_stepresult_has_required_fields(self) -> None:
        hints = get_type_hints(StepResult, include_extras=True)
        expected = {"step_id", "output_chunks", "generated_sql", "bound_inputs", "verification", "narration"}
        assert expected == set(hints.keys())

    def test_stepresult_valid_dict(self) -> None:
        result: StepResult = {
            "step_id": "s1",
            "output_chunks": [{"text": "row 1", "source_id": "abc"}],
            "generated_sql": "SELECT * FROM sales LIMIT 100",
            "bound_inputs": {"refs": {"s0.output": "value"}, "truncated": False},
            "verification": {"verdict": "acceptable", "reason": "ok", "checks": {}},
            "narration": "Found 1 record.",
        }
        assert result["step_id"] == "s1"
        assert result["verification"]["verdict"] == "acceptable"

    def test_stepresult_nullable_optional_fields(self) -> None:
        result: StepResult = {
            "step_id": "s2",
            "output_chunks": [],
            "generated_sql": None,
            "bound_inputs": None,
            "verification": {"verdict": "unacceptable", "reason": "empty", "checks": {}},
            "narration": "No results found.",
        }
        assert result["generated_sql"] is None
        assert result["bound_inputs"] is None

    def test_stepresult_all_verdict_literals(self) -> None:
        for verdict in ("acceptable", "partial", "unacceptable"):
            result: StepResult = {
                "step_id": "s1",
                "output_chunks": [],
                "generated_sql": None,
                "bound_inputs": None,
                "verification": {"verdict": verdict, "reason": "x", "checks": {}},  # type: ignore[typeddict-item]
                "narration": "x",
            }
            assert result["verification"]["verdict"] == verdict

    def test_stepresult_narration_is_string(self) -> None:
        result: StepResult = {
            "step_id": "s1",
            "output_chunks": [],
            "generated_sql": None,
            "bound_inputs": None,
            "verification": {"verdict": "partial", "reason": "partial", "checks": {"rows": 3}},
            "narration": "Partial results available.",
        }
        assert isinstance(result["narration"], str)


class TestAgentStatePlanFields:
    def _hints(self) -> dict:
        return get_type_hints(AgentState, include_extras=True)

    def test_has_raw_user_intent(self) -> None:
        assert "raw_user_intent" in self._hints()

    def test_has_plan(self) -> None:
        assert "plan" in self._hints()

    def test_has_past_steps(self) -> None:
        assert "past_steps" in self._hints()

    def test_has_current_step(self) -> None:
        assert "current_step" in self._hints()

    def test_has_plan_revision(self) -> None:
        assert "plan_revision" in self._hints()

    def test_has_budget(self) -> None:
        assert "budget" in self._hints()

    def test_no_top_level_narration(self) -> None:
        """narration belongs to StepResult only — no AgentState top-level field."""
        assert "narration" not in self._hints()

    def test_no_clarification_pending(self) -> None:
        """Domain rule: clarification is terminal SSE — no cross-turn pending field."""
        assert "clarification_pending" not in self._hints()

    def test_token_reducers_preserved(self) -> None:
        """T-050 additive reducers must survive the state.py edit."""
        hints = self._hints()
        assert "total_input_tokens" in hints
        assert "total_output_tokens" in hints
