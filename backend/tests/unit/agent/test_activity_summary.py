"""Unit tests for the pure compact activity-summary builder (T-058 / FR-018).

``build_activity_summary`` distils a finished agentic turn's ``AgentState`` into
the compact shape persisted on ``chat_messages.activity_summary`` and emitted on
the ``done`` SSE event (data-model §3). All inputs here are SYNTHETIC.

Coverage:
  * Non-agentic turn (no plan / past_steps / superseded) → None.
  * Compact shape + step/source counts for a clean single-step turn.
  * cost_label thresholds (small / medium / large) from the budget fraction.
  * 200-char caps + control/BiDi sanitisation on roles[].line and labels.
  * Replan turn → had_replan, superseded_plan, revision_reason populated.
  * had_failure on retry (same step twice) / unacceptable verdict / budget_hit.
"""
from __future__ import annotations

from typing import Any

from src.agent.activity_summary import build_activity_summary


def _budget(**overrides: Any) -> dict[str, Any]:
    base = {
        "max_steps": 5,
        "max_retries_per_step": 1,
        "max_revisions": 1,
        "token_ceiling": 34_000,
        "deadline": None,
    }
    base.update(overrides)
    return base


def _step(step_id: str, *, source_id: str = "src-1", description: str = "do a thing") -> dict[str, Any]:
    return {
        "id": step_id,
        "description": description,
        "source_id": source_id,
        "sub_query": f"q for {step_id}",
        "depends_on": [],
        "status": "pending",
        "retry_count": 0,
    }


def _result(step_id: str, *, verdict: str = "acceptable", narration: str = "Got 1 result.") -> dict[str, Any]:
    return {
        "step_id": step_id,
        "output_chunks": [],
        "generated_sql": None,
        "bound_inputs": None,
        "verification": {"verdict": verdict, "reason": "ok", "checks": {}},
        "narration": narration,
    }


# ---------------------------------------------------------------------------
# Non-agentic → None
# ---------------------------------------------------------------------------


class TestNonAgentic:
    def test_empty_state_returns_none(self) -> None:
        assert build_activity_summary({}) is None

    def test_v2_state_without_plan_returns_none(self) -> None:
        state = {
            "total_input_tokens": 1000,
            "total_output_tokens": 200,
            "retrieved_chunks": [{"text": "x"}],
        }
        assert build_activity_summary(state) is None


# ---------------------------------------------------------------------------
# Compact shape
# ---------------------------------------------------------------------------


class TestCompactShape:
    def test_single_step_clean_turn(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("s1"),
            "past_steps": [_result("s1", verdict="acceptable")],
            "plan_revision": 0,
            "total_input_tokens": 9120,
            "total_output_tokens": 1480,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        # All documented keys present.
        for key in (
            "step_count", "source_count", "had_replan", "had_failure",
            "budget_hit", "turn_tokens", "cost_label", "plan",
            "superseded_plan", "revision_reason", "roles",
        ):
            assert key in summary
        assert summary["step_count"] == 1
        assert summary["source_count"] == 1
        assert summary["had_replan"] is False
        assert summary["had_failure"] is False
        assert summary["budget_hit"] is False
        assert summary["turn_tokens"] == {"input": 9120, "output": 1480}
        assert summary["superseded_plan"] is None
        assert summary["revision_reason"] is None
        assert summary["plan"][0]["id"] == "s1"
        assert summary["plan"][0]["status"] == "done"

    def test_pending_plan_steps_counted(self) -> None:
        state = {
            "plan": [_step("s2"), _step("s3")],
            "current_step": _step("s1"),
            "past_steps": [_result("s1")],
            "plan_revision": 0,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        # 1 executed + 2 pending = 3 distinct rows.
        assert summary["step_count"] == 3
        ids = [row["id"] for row in summary["plan"]]
        assert ids == ["s1", "s2", "s3"]


# ---------------------------------------------------------------------------
# cost_label thresholds
# ---------------------------------------------------------------------------


class TestCostLabel:
    def _summary_for_spend(self, total: int) -> dict[str, Any]:
        state = {
            "past_steps": [_result("s1")],
            "current_step": _step("s1"),
            "plan": [],
            "total_input_tokens": total,
            "total_output_tokens": 0,
            "budget": _budget(token_ceiling=1000),
        }
        s = build_activity_summary(state)
        assert s is not None
        return s

    def test_small_below_34pct(self) -> None:
        assert self._summary_for_spend(100)["cost_label"] == "small"

    def test_medium_between_34_and_67pct(self) -> None:
        assert self._summary_for_spend(500)["cost_label"] == "medium"

    def test_large_above_67pct(self) -> None:
        assert self._summary_for_spend(800)["cost_label"] == "large"

    def test_no_ceiling_defaults_small(self) -> None:
        state = {
            "past_steps": [_result("s1")],
            "current_step": _step("s1"),
            "plan": [],
            "total_input_tokens": 999_999,
            "total_output_tokens": 999_999,
            "budget": _budget(token_ceiling=0),
        }
        s = build_activity_summary(state)
        assert s is not None
        assert s["cost_label"] == "small"


# ---------------------------------------------------------------------------
# Sanitisation + caps (security rule 5)
# ---------------------------------------------------------------------------


class TestSanitisationAndCaps:
    def test_role_lines_capped_at_200(self) -> None:
        long = "A" * 500
        state = {
            "plan": [],
            "current_step": _step("s1", description=long),
            "past_steps": [_result("s1", narration=long)],
            "plan_revision": 0,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        for role in summary["roles"]:
            assert len(role.get("line", "")) <= 200
        for row in summary["plan"]:
            assert len(row["label"]) <= 200

    def test_control_chars_stripped_from_label(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("s1", description="evil\r\n\x00‮inject"),
            "past_steps": [_result("s1", narration="line\nbreak")],
            "plan_revision": 0,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        label = summary["plan"][0]["label"]
        assert "\r" not in label
        assert "\n" not in label
        assert "\x00" not in label
        assert "‮" not in label


# ---------------------------------------------------------------------------
# Replan
# ---------------------------------------------------------------------------


class TestReplan:
    def test_replan_populates_superseded_and_reason(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("r1"),
            "past_steps": [_result("r1", verdict="acceptable")],
            "plan_revision": 1,
            "plan_revision_reason": "first plan returned no rows",
            "superseded_plan": [_step("s1"), _step("s2")],
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        assert summary["had_replan"] is True
        assert summary["revision_reason"] == "first plan returned no rows"
        assert summary["superseded_plan"] is not None
        assert [row["id"] for row in summary["superseded_plan"]] == ["s1", "s2"]
        # A planner "revised the plan" role line is present.
        assert any(
            r["role"] == "planner" and "revised the plan" in r["line"]
            for r in summary["roles"]
        )


# ---------------------------------------------------------------------------
# had_failure detection
# ---------------------------------------------------------------------------


class TestHadFailure:
    def test_retry_same_step_twice_flags_failure(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("s1"),
            "past_steps": [
                _result("s1", verdict="unacceptable"),
                _result("s1", verdict="acceptable"),  # retry succeeded
            ],
            "plan_revision": 0,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        assert summary["had_failure"] is True

    def test_unacceptable_verdict_flags_failure(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("s1"),
            "past_steps": [_result("s1", verdict="unacceptable")],
            "plan_revision": 0,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        assert summary["had_failure"] is True

    def test_budget_hit_flags_failure_and_budget(self) -> None:
        state = {
            "plan": [],
            "current_step": _step("s1"),
            "past_steps": [_result("s1", verdict="acceptable")],
            "plan_revision": 0,
            "budget_hit": True,
            "budget": _budget(),
        }
        summary = build_activity_summary(state)
        assert summary is not None
        assert summary["budget_hit"] is True
        assert summary["had_failure"] is True
        assert any(r["role"] == "budget" for r in summary["roles"])
