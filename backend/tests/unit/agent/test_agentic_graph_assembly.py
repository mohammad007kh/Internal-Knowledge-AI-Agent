"""Unit tests for T-058: agentic graph assembly + flag-driven selection.

Asserts the flag selects the right topology and that the agentic graph wires
its nodes/edges per the assembled plan-and-execute topology:

* Flag OFF (or non-sandbox) → the v2 topology (rollback path) is built — no
  agentic nodes (planner / execute_step / verify_step / budget gates).
* Flag ON + sandbox → the agentic topology — planner entry, the executor↔verify
  loop, both budget gates, replan, and guardrail input/output wrapping the WHOLE
  graph unconditionally (Constitution IV). The reflector is NOT inserted.

These are topology assertions (``pipeline.get_graph().nodes/edges``); no LLM is
invoked. Mirrors ``tests/integration/agent/test_pipeline_v2.py``'s edge-set style.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import pipeline as pipeline_mod
from src.agent.pipeline import build_agent_budget_snapshot, build_pipeline


def _build(*, agentic: bool, sandbox: bool, guardrail: bool, monkeypatch):
    """Build a pipeline with the agentic flag forced on/off, returning the graph."""
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_AGENTIC_ENABLED", agentic)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_V2_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_REFLECTOR_ENABLED", False)

    resolver = AsyncMock()
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())
    chunk_repo = AsyncMock()
    chat_session_repo = AsyncMock()
    chat_msg_repo = AsyncMock()
    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()
    source_repo = AsyncMock()
    guardrail_service = MagicMock() if guardrail else None

    return build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_msg_repo,
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=guardrail_service,
        source_repository=source_repo,
        sandbox=sandbox,
    )


def _nodes_edges(compiled):
    graph = compiled.get_graph()
    nodes = set(graph.nodes)
    edges = [(e.source, e.target) for e in graph.edges]
    return nodes, edges


# ---------------------------------------------------------------------------
# Flag OFF → v2 topology (rollback path unchanged)
# ---------------------------------------------------------------------------


class TestFlagOffSelectsV2:
    def test_flag_off_builds_v2_not_agentic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        compiled = _build(agentic=False, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        nodes, _ = _nodes_edges(compiled)
        # v2 hallmark nodes present.
        assert {"query_analyzer", "source_router", "retrieve_context"} <= nodes
        # Agentic nodes absent (the v2 graph is the rollback).
        assert "planner" not in nodes
        assert "execute_step" not in nodes
        assert "verify_step" not in nodes
        assert "budget_guard_step" not in nodes

    def test_flag_on_but_not_sandbox_builds_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sandbox-first: flag ON but the non-sandbox path still gets v2."""
        compiled = _build(agentic=True, sandbox=False, guardrail=True, monkeypatch=monkeypatch)
        nodes, _ = _nodes_edges(compiled)
        assert "planner" not in nodes
        assert "query_analyzer" in nodes


# ---------------------------------------------------------------------------
# Flag ON + sandbox → agentic topology
# ---------------------------------------------------------------------------


class TestFlagOnSandboxSelectsAgentic:
    def test_agentic_node_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        nodes, _ = _nodes_edges(compiled)
        expected = {
            "load_history",
            "planner",
            "budget_guard_step",
            "budget_guard_replan",
            "advance_step",
            "execute_step",
            "verify_step",
            "replan",
            "synthesize_failure",
            "generate_response",
            "format_response",
        }
        assert expected <= nodes
        # v2-only nodes are NOT part of the agentic graph.
        assert "query_analyzer" not in nodes
        assert "source_router" not in nodes

    def test_reflector_not_inserted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constitution: reflector stays default-OFF / untouched in the agentic graph."""
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        nodes, _ = _nodes_edges(compiled)
        assert "reflector" not in nodes

    def test_planner_is_entry_after_history_and_guardrail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        _, edges = _nodes_edges(compiled)
        # Guardrail input wraps the front of the graph (no bypass).
        assert ("load_history", "guardrail_input") in edges
        assert ("guardrail_input", "planner") in edges

    def test_executor_verify_loop_and_budget_gates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        _, edges = _nodes_edges(compiled)
        # budget gate → dispatch → execute → verify
        assert ("budget_guard_step", "advance_step") in edges
        assert ("advance_step", "execute_step") in edges
        assert ("execute_step", "verify_step") in edges
        # verify OWNS the R4b conditional edge: success → synthesizer, retry/next
        # → step budget gate, replan → replan budget gate, exhausted → failure.
        assert ("verify_step", "generate_response") in edges
        assert ("verify_step", "budget_guard_step") in edges
        assert ("verify_step", "budget_guard_replan") in edges
        assert ("verify_step", "synthesize_failure") in edges
        # replan is gated by its own budget node and re-enters the step gate.
        assert ("budget_guard_replan", "replan") in edges
        assert ("replan", "budget_guard_step") in edges

    def test_guardrails_wrap_output_unconditionally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        _, edges = _nodes_edges(compiled)
        # The ONLY terminal path runs through guardrail_output (no bypass).
        assert ("format_response", "guardrail_output") in edges
        assert ("generate_response", "format_response") in edges
        # generate_response must NOT short-circuit to END around the guardrail.
        assert ("generate_response", "__end__") not in edges
        assert ("format_response", "__end__") not in edges

    def test_budget_breach_routes_to_failure_synthesis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled = _build(agentic=True, sandbox=True, guardrail=True, monkeypatch=monkeypatch)
        _, edges = _nodes_edges(compiled)
        assert ("budget_guard_step", "synthesize_failure") in edges
        assert ("budget_guard_replan", "synthesize_failure") in edges
        assert ("synthesize_failure", "generate_response") in edges

    def test_agentic_without_guardrail_still_terminates_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No guardrail service → graph still ends at format_response (no orphan)."""
        compiled = _build(agentic=True, sandbox=True, guardrail=False, monkeypatch=monkeypatch)
        nodes, edges = _nodes_edges(compiled)
        assert "guardrail_input" not in nodes
        assert "guardrail_output" not in nodes
        assert ("load_history", "planner") in edges
        assert ("format_response", "__end__") in edges


# ---------------------------------------------------------------------------
# Budget snapshot helper
# ---------------------------------------------------------------------------


class TestBudgetSnapshot:
    def test_snapshot_maps_settings_to_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_PLAN_STEPS", 5)
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_STEP_RETRIES", 1)
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_MAX_PLAN_REVISIONS", 1)
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_TOKEN_CEILING_INPUT", 30000)
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_TOKEN_CEILING_OUTPUT", 4000)
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_TURN_DEADLINE_SECS", None)
        snap = build_agent_budget_snapshot()
        assert snap["max_steps"] == 5
        assert snap["max_retries_per_step"] == 1
        assert snap["max_revisions"] == 1
        assert snap["token_ceiling"] == 34000
        assert snap["deadline"] is None

    def test_snapshot_deadline_is_absolute_iso_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pipeline_mod.settings, "AGENT_TURN_DEADLINE_SECS", 30)
        snap = build_agent_budget_snapshot()
        assert isinstance(snap["deadline"], str)
        # Parseable ISO-8601 — the guard parses it with datetime.fromisoformat.
        from datetime import datetime

        datetime.fromisoformat(snap["deadline"])
