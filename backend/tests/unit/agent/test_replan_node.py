"""Unit tests for T-056: replan node.

Covers the single-allowed whole-plan revision:
  - 0→1 revision cap guard (second replan impossible).
  - Event sequence: ``replan`` then ``plan(revision:1)``; reason identical across
    both and equal to the carried verifier reason.
  - Server-side permission assertion (Security Rule 2) BEFORE the new plan event;
    an out-of-permitted-set source_id drops to honest-failure (no plan event).
  - Superseded plan retained in state.
  - Token delta returned; ``planner`` Langfuse span opened/closed.
  - Immutability: the input plan/state is never mutated in place.

Synthetic-only fixtures (public repo): model name "test-model-stub", no real PII.
"""
from __future__ import annotations

import copy
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.replan import replan_step

# ---------------------------------------------------------------------------
# Fixtures / helpers (synthetic only)
# ---------------------------------------------------------------------------

PERMITTED_SOURCES: list[dict[str, Any]] = [
    {
        "id": "src-001",
        "name": "Synthetic Source A",
        "purpose": "Synthetic purpose A.",
        "examples": "Example A1; Example A2",
        "out_of_scope": "Out of scope A",
        "data_source": "synthetic",
    },
    {
        "id": "src-002",
        "name": "Synthetic Source B",
        "purpose": "Synthetic purpose B.",
        "examples": "Example B1; Example B2",
        "out_of_scope": "Out of scope B",
        "data_source": "synthetic",
    },
]
PERMITTED_IDS = [s["id"] for s in PERMITTED_SOURCES]

CARRIED_REASON = "previous query returned no rows; broaden the filter"


def _make_response(payload: dict[str, Any], in_tok: int = 11, out_tok: int = 22) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = in_tok
    usage.completion_tokens = out_tok
    choice = MagicMock()
    choice.message.content = json.dumps(payload)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_resolver(payload: dict[str, Any], in_tok: int = 11, out_tok: int = 22) -> MagicMock:
    client = MagicMock()
    client.model_id = "test-model-stub"
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


def _superseded_plan() -> list[dict[str, Any]]:
    return [
        {
            "id": "s1",
            "description": "Old step",
            "source_id": "src-001",
            "sub_query": "old sub query",
            "depends_on": [],
            "status": "failed",
            "retry_count": 1,
            "data_source": "synthetic",
        }
    ]


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trace_id": "trace-test-056",
        "source_ids": list(PERMITTED_IDS),
        "raw_user_intent": "Synthetic question that needs revising.",
        "plan_revision": 0,
        "plan": _superseded_plan(),
        "current_step": {
            "id": "s1",
            "description": "Old step",
            "source_id": "src-001",
            "sub_query": "old sub query",
            "depends_on": [],
            "status": "failed",
            "retry_count": 1,
        },
        "past_steps": [
            {
                "step_id": "s1",
                "output_chunks": [],
                "generated_sql": None,
                "bound_inputs": None,
                "verification": {
                    "verdict": "unacceptable",
                    "reason": CARRIED_REASON,
                    "checks": {},
                },
                "narration": "",
            }
        ],
        "data_source": "synthetic",
    }
    base.update(kwargs)
    return base


def _langfuse() -> MagicMock:
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


def _plan_payload(n: int, source_id: str = "src-001") -> dict[str, Any]:
    return {
        "decision": "plan",
        "steps": [
            {
                "id": f"s{i + 1}",
                "label": f"Revised step {i + 1}",
                "source_id": source_id,
                "sub_query": f"revised sub query {i + 1}",
                "depends_on": [],
            }
            for i in range(n)
        ],
    }


_NOOP_PROMPT = "{SOURCES_BLOCK}|{FAILURE_REASON}|{SUPERSEDED_PLAN}"


def _patch_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.agent.nodes.replan.load_prompt", lambda *a, **kw: _NOOP_PROMPT
    )


# ---------------------------------------------------------------------------
# Revision cap guard (FR-007)
# ---------------------------------------------------------------------------


class TestRevisionCap:
    @pytest.mark.asyncio
    async def test_second_replan_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """plan_revision==1 on entry → no second revision; LLM not called, no plan event."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(plan_revision=1),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        # No LLM revision performed.
        resolver.resolve.assert_not_called()
        assert "plan_event_data" not in result
        assert "replan_event_data" not in result

    @pytest.mark.asyncio
    async def test_entry_sets_revision_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On a valid first revision the node sets plan_revision = 1."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["plan_revision"] == 1


# ---------------------------------------------------------------------------
# Event sequence + reason propagation
# ---------------------------------------------------------------------------


class TestEventSequenceAndReason:
    @pytest.mark.asyncio
    async def test_emits_replan_then_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Node emits a replan event and a fresh plan(revision:1) event."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "replan_event_data" in result
        assert "plan_event_data" in result
        assert result["replan_event_data"]["superseded_revision"] == 0
        assert result["plan_event_data"]["revision"] == 1

    @pytest.mark.asyncio
    async def test_reason_identical_and_matches_verifier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason is identical across both events and equals the verifier reason."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        replan_reason = result["replan_event_data"]["reason"]
        plan_reason = result["plan_event_data"]["reason"]
        assert replan_reason == plan_reason == CARRIED_REASON
        assert result["plan_revision_reason"] == CARRIED_REASON

    @pytest.mark.asyncio
    async def test_reason_falls_back_to_plan_revision_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no verification reason is present, plan_revision_reason is used."""
        resolver = _make_resolver(_plan_payload(1))
        _patch_prompt(monkeypatch)
        state = _state(past_steps=[], plan_revision_reason="fallback reason")

        result = await replan_step(
            state,
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["replan_event_data"]["reason"] == "fallback reason"
        assert result["plan_event_data"]["reason"] == "fallback reason"

    @pytest.mark.asyncio
    async def test_fresh_plan_step_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The new plan list contains PlanStep-shaped dicts (pending, retry_count 0)."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert len(result["plan"]) == 2
        for step in result["plan"]:
            assert step["status"] == "pending"
            assert step["retry_count"] == 0
            assert step["source_id"] in PERMITTED_IDS

    @pytest.mark.asyncio
    async def test_plan_event_step_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each plan_event_data step carries id/label/source_id/source_name/depends_on."""
        resolver = _make_resolver(_plan_payload(1, source_id="src-002"))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        step = result["plan_event_data"]["steps"][0]
        assert step["source_id"] == "src-002"
        assert step["source_name"] == "Synthetic Source B"
        assert "label" in step
        assert "depends_on" in step


# ---------------------------------------------------------------------------
# Cap enforcement (≤5 steps)
# ---------------------------------------------------------------------------


class TestStepCap:
    @pytest.mark.asyncio
    async def test_six_steps_capped_to_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolver = _make_resolver(_plan_payload(6))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert len(result["plan"]) == 5
        assert len(result["plan_event_data"]["steps"]) == 5


# ---------------------------------------------------------------------------
# Permission assertion / Security Rule 2
# ---------------------------------------------------------------------------


class TestPermissionAssertion:
    @pytest.mark.asyncio
    async def test_out_of_set_source_id_honest_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An out-of-set source_id trips the assertion → honest-failure, no plan event."""
        payload = {
            "decision": "plan",
            "steps": [
                {
                    "id": "s1",
                    "label": "Evil",
                    "source_id": "src-EVIL-not-permitted",
                    "sub_query": "q",
                    "depends_on": [],
                }
            ],
        }
        resolver = _make_resolver(payload)
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" not in result
        assert "plan_event_data" not in result
        assert "replan_event_data" not in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mixed_one_violation_honest_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even one violating source_id triggers honest-failure."""
        payload = {
            "decision": "plan",
            "steps": [
                {"id": "s1", "label": "Good", "source_id": "src-001", "sub_query": "q", "depends_on": []},
                {"id": "s2", "label": "Bad", "source_id": "src-EVIL", "sub_query": "q2", "depends_on": []},
            ],
        }
        resolver = _make_resolver(payload)
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert "plan" not in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_honest_failure_still_retains_superseded_and_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On a permission violation the revision cap + superseded plan are still set."""
        payload = {
            "decision": "plan",
            "steps": [
                {"id": "s1", "label": "Bad", "source_id": "src-EVIL", "sub_query": "q", "depends_on": []},
            ],
        }
        resolver = _make_resolver(payload)
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["plan_revision"] == 1
        assert result["superseded_plan"] == _superseded_plan()


# ---------------------------------------------------------------------------
# Superseded plan retention
# ---------------------------------------------------------------------------


class TestSupersededRetention:
    @pytest.mark.asyncio
    async def test_superseded_plan_retained(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["superseded_plan"] == _superseded_plan()


# ---------------------------------------------------------------------------
# Token delta + Langfuse span + immutability
# ---------------------------------------------------------------------------


class TestTokenSpanImmutability:
    @pytest.mark.asyncio
    async def test_token_deltas_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolver = _make_resolver(_plan_payload(1), in_tok=33, out_tok=44)
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["total_input_tokens"] == 33
        assert result["total_output_tokens"] == 44

    @pytest.mark.asyncio
    async def test_token_deltas_present_on_honest_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "decision": "plan",
            "steps": [
                {"id": "s1", "label": "Bad", "source_id": "src-EVIL", "sub_query": "q", "depends_on": []},
            ],
        }
        resolver = _make_resolver(payload, in_tok=5, out_tok=6)
        _patch_prompt(monkeypatch)

        result = await replan_step(
            _state(),
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert result["total_input_tokens"] == 5
        assert result["total_output_tokens"] == 6

    @pytest.mark.asyncio
    async def test_langfuse_span_opened_and_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolver = _make_resolver(_plan_payload(1))
        _patch_prompt(monkeypatch)
        lf = _langfuse()

        await replan_step(
            _state(),
            langfuse=lf,
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        lf.span.assert_called_once()
        lf.span.return_value.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_span_closed_on_llm_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolver = _make_resolver(_plan_payload(1))
        resolver.resolve = AsyncMock(side_effect=RuntimeError("boom"))
        _patch_prompt(monkeypatch)
        lf = _langfuse()

        result = await replan_step(
            _state(),
            langfuse=lf,
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        lf.span.return_value.end.assert_called_once()
        assert "error" in result
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_input_state_not_mutated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The node must not mutate the incoming state/plan in place."""
        resolver = _make_resolver(_plan_payload(2))
        _patch_prompt(monkeypatch)
        state = _state()
        snapshot = copy.deepcopy(state)

        await replan_step(
            state,
            langfuse=_langfuse(),
            ai_model_resolver=resolver,
            source_meta_loader=_fake_meta_loader,
        )

        assert state == snapshot
