"""Unit tests for T-052: planner node — cap enforcement, permission assertion, event shape."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.planner import plan_query
from src.schemas.chat import StreamEventType

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PERMITTED_SOURCES: list[dict[str, Any]] = [
    {
        "id": "src-001",
        "name": "Sales DB",
        "purpose": "Sales tracking and revenue reporting.",
        "examples": "Monthly revenue; Top 10 products",
        "out_of_scope": "Customer PII",
    },
    {
        "id": "src-002",
        "name": "HR Policies",
        "purpose": "HR procedures and guidelines.",
        "examples": "Leave policy; Onboarding checklist",
        "out_of_scope": "Salary data",
    },
    {
        "id": "src-003",
        "name": "Finance Report",
        "purpose": "Financial summaries and quarterly results.",
        "examples": "Q3 results; Budget overview",
        "out_of_scope": "Bank details",
    },
]
PERMITTED_IDS = [s["id"] for s in PERMITTED_SOURCES]


def _make_response(payload: dict[str, Any], in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = in_tok
    usage.completion_tokens = out_tok
    choice = MagicMock()
    choice.message.content = json.dumps(payload)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_resolver(payload: dict[str, Any], in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    client = MagicMock()
    client.model_id = "gpt-4o-mini"
    client.temperature = 0.0
    client.max_tokens = 1024
    client.custom_prompt = None
    client.http_client.chat.completions.create = AsyncMock(
        return_value=_make_response(payload, in_tok, out_tok)
    )
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=client)
    return resolver


async def _fake_meta_loader(ids: list[str]) -> list[dict[str, Any]]:
    return [s for s in PERMITTED_SOURCES if s["id"] in ids]


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trace_id": "trace-test-052",
        "source_ids": PERMITTED_IDS,
        "raw_user_intent": "What were last quarter's sales by region?",
        "plan_revision": 0,
    }
    base.update(kwargs)
    return base


def _langfuse() -> MagicMock:
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


def _plan_payload(n: int, source_id: str = "src-001") -> dict[str, Any]:
    """Build a 'plan' LLM payload with n steps."""
    return {
        "decision": "plan",
        "steps": [
            {
                "id": f"s{i + 1}",
                "label": f"Step {i + 1}",
                "source_id": source_id,
                "sub_query": f"sub query {i + 1}",
                "depends_on": [],
            }
            for i in range(n)
        ],
    }


# ---------------------------------------------------------------------------
# Cap enforcement (FR-007)
# ---------------------------------------------------------------------------


class TestCapEnforcement:
    @pytest.mark.asyncio
    async def test_six_steps_capped_to_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM returns 6 steps — node must cap to ≤5."""
        resolver = _make_resolver(_plan_payload(6))
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" in result
        assert len(result["plan"]) <= 5

    @pytest.mark.asyncio
    async def test_exactly_five_steps_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 5-step plan is kept as-is — cap must not trim below limit."""
        resolver = _make_resolver(_plan_payload(5))
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" in result
        assert len(result["plan"]) == 5

    @pytest.mark.asyncio
    async def test_one_step_plan_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolver = _make_resolver(_plan_payload(1))
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" in result
        assert len(result["plan"]) == 1


# ---------------------------------------------------------------------------
# Permission assertion / Security Rule 2
# ---------------------------------------------------------------------------


class TestPermissionAssertion:
    @pytest.mark.asyncio
    async def test_out_of_set_source_id_routes_to_honest_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An out-of-set source_id must trigger honest-failure — no plan event."""
        payload = {
            "decision": "plan",
            "steps": [
                {
                    "id": "s1",
                    "label": "Evil step",
                    "source_id": "src-EVIL-not-permitted",
                    "sub_query": "query",
                    "depends_on": [],
                }
            ],
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" not in result
        assert "plan_event_data" not in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mixed_one_violation_routes_to_honest_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even one violating source_id in a multi-step plan triggers honest-failure."""
        payload = {
            "decision": "plan",
            "steps": [
                {"id": "s1", "label": "Good", "source_id": "src-001", "sub_query": "q", "depends_on": []},
                {"id": "s2", "label": "Bad", "source_id": "src-EVIL", "sub_query": "q2", "depends_on": ["s1"]},
            ],
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" not in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_all_permitted_source_ids_emit_plan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When all source_ids are in the permitted set, the plan is returned."""
        payload = {
            "decision": "plan",
            "steps": [
                {"id": "s1", "label": "Sales", "source_id": "src-001", "sub_query": "total sales", "depends_on": []},
                {"id": "s2", "label": "HR", "source_id": "src-002", "sub_query": "headcount", "depends_on": []},
            ],
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" in result
        assert "error" not in result


# ---------------------------------------------------------------------------
# Plan event payload shape
# ---------------------------------------------------------------------------


class TestPlanEventShape:
    @pytest.mark.asyncio
    async def test_plan_event_data_contract_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """plan_event_data must have revision, reason, and steps list."""
        payload = {
            "decision": "plan",
            "steps": [
                {
                    "id": "s1",
                    "label": "Sales by region",
                    "source_id": "src-001",
                    "sub_query": "revenue by region",
                    "depends_on": [],
                }
            ],
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan_event_data" in result
        event = result["plan_event_data"]
        assert "revision" in event
        assert "reason" in event
        assert "steps" in event

    @pytest.mark.asyncio
    async def test_plan_event_step_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each step in plan_event_data must carry id/label/source_id/source_name/depends_on."""
        payload = {
            "decision": "plan",
            "steps": [
                {
                    "id": "s1",
                    "label": "Fetch HR data",
                    "source_id": "src-002",
                    "sub_query": "headcount per department",
                    "depends_on": [],
                }
            ],
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        step = result["plan_event_data"]["steps"][0]
        assert step["id"] == "s1"
        assert step["label"] == "Fetch HR data"
        assert step["source_id"] == "src-002"
        assert step["source_name"] == "HR Policies"
        assert step["depends_on"] == []

    @pytest.mark.asyncio
    async def test_plan_step_planstep_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The 'plan' list must contain PlanStep-shaped dicts with required fields."""
        payload = _plan_payload(2)
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        for step in result["plan"]:
            assert "id" in step
            assert "description" in step
            assert "source_id" in step
            assert "sub_query" in step
            assert "depends_on" in step
            assert "status" in step
            assert "retry_count" in step
            assert step["status"] == "pending"

    @pytest.mark.asyncio
    async def test_token_deltas_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The node must return total_input_tokens and total_output_tokens deltas."""
        resolver = _make_resolver(_plan_payload(1), in_tok=15, out_tok=30)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["total_input_tokens"] == 15
        assert result["total_output_tokens"] == 30


# ---------------------------------------------------------------------------
# Clarify-with-options (FR-014 trigger)
# ---------------------------------------------------------------------------


class TestClarifyWithOptions:
    @pytest.mark.asyncio
    async def test_ambiguous_question_returns_clarification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ambiguous LLM decision must set requires_clarification=True with options."""
        payload = {
            "decision": "needs_clarification",
            "question": "Which data source would you like to explore?",
            "options": [
                {"label": "Sales data", "source_id": "src-001"},
                {"label": "HR policies", "source_id": "src-002"},
            ],
            "allow_free_text": True,
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result.get("requires_clarification") is True
        assert "clarification_question" in result
        options = result.get("clarification_options", [])
        assert 2 <= len(options) <= 4

    @pytest.mark.asyncio
    async def test_clarification_options_filtered_to_permitted_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Options with out-of-set source_ids must be silently dropped."""
        payload = {
            "decision": "needs_clarification",
            "question": "Which source?",
            "options": [
                {"label": "Sales", "source_id": "src-001"},
                {"label": "Evil", "source_id": "src-EVIL-not-permitted"},
            ],
            "allow_free_text": True,
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        options = result.get("clarification_options", [])
        option_ids = {opt["source_id"] for opt in options}
        assert "src-EVIL-not-permitted" not in option_ids
        assert "src-001" in option_ids

    @pytest.mark.asyncio
    async def test_clarification_options_capped_at_four(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if LLM returns 5+ options, only 2-4 are kept."""
        payload = {
            "decision": "needs_clarification",
            "question": "Which?",
            "options": [
                {"label": f"Option {i}", "source_id": "src-001"}
                for i in range(6)
            ],
            "allow_free_text": True,
        }
        resolver = _make_resolver(payload)
        monkeypatch.setattr("src.agent.nodes.planner.load_prompt", lambda *a, **kw: "{SOURCES_BLOCK}")

        result = await plan_query(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        options = result.get("clarification_options", [])
        assert len(options) <= 4


# ---------------------------------------------------------------------------
# StreamEventType schema: four new members (T-052 owns the enum additions)
# ---------------------------------------------------------------------------


class TestStreamEventTypeSchema:
    def test_plan_member_value(self) -> None:
        assert StreamEventType.PLAN == "plan"

    def test_step_member_value(self) -> None:
        assert StreamEventType.STEP == "step"

    def test_replan_member_value(self) -> None:
        assert StreamEventType.REPLAN == "replan"

    def test_budget_member_value(self) -> None:
        assert StreamEventType.BUDGET == "budget"
