"""Tests for execute_step node (T-053).

Acceptance criteria:
- {{s1.output}} with 60-item list → 50 items comma-joined, truncated=True.
- Inaccessible step source_id → fails without naming the inaccessible source.
- started + finished events emitted with the contract shape.
- summary is narration, not raw rows (Security Rule 5).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.nodes.executor import (
    _MAX_REF_ITEMS,
    _NARRATION_MAX,
    _interpolate,
    _narrate,
    execute_step,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_step_result(step_id: str, chunks: list[dict]) -> dict:
    return {
        "step_id": step_id,
        "output_chunks": chunks,
        "generated_sql": None,
        "bound_inputs": None,
        "verification": {"verdict": "partial", "reason": "", "checks": {}},
        "narration": "",
    }


def _make_plan_step(
    id: str,
    source_id: str,
    sub_query: str = "Describe the data.",
    description: str = "Step description",
) -> dict:
    return {
        "id": id,
        "description": description,
        "source_id": source_id,
        "sub_query": sub_query,
        "depends_on": [],
        "status": "active",
        "retry_count": 0,
    }


def _make_state(**overrides) -> dict:
    base: dict = {
        "trace_id": "trace-abc",
        "source_ids": ["src-1"],
        "plan": [_make_plan_step("s1", "src-1")],
        "current_step": _make_plan_step("s1", "src-1"),
        "past_steps": [],
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


def _mock_embedding_factory(embedding: list[float] | None = None) -> AsyncMock:
    factory = AsyncMock()
    service = AsyncMock()
    service.embed_query.return_value = embedding or [0.1] * 10
    factory.for_active.return_value = (service, "embedder-1")
    return factory


def _mock_chunk_repo(results: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.similarity_search.return_value = results or []
    return repo


def _make_chunk_orm(chunk_id: str, text: str, source_id: str = "src-1") -> MagicMock:
    c = MagicMock()
    c.id = chunk_id
    c.source_id = source_id
    c.chunk_text = text
    c.metadata_ = {
        "document_title": f"Doc {chunk_id}",
        "page_number": None,
        "source_name": "Test Source",
    }
    return c


# ---------------------------------------------------------------------------
# R1b interpolation
# ---------------------------------------------------------------------------


class TestR1bInterpolation:
    """{{sN.output}} binding per data-model §2b."""

    def test_60_items_truncated_to_50(self):
        chunks = [{"text": f"item{i}"} for i in range(60)]
        past = [_make_step_result("s1", chunks)]
        resolved, bound = _interpolate("Query: {{s1.output}}", past)

        assert bound is not None
        assert bound["truncated"] is True
        items_in_result = resolved.replace("Query: ", "").split(", ")
        assert len(items_in_result) == _MAX_REF_ITEMS

    def test_50_items_not_truncated(self):
        chunks = [{"text": f"item{i}"} for i in range(50)]
        past = [_make_step_result("s1", chunks)]
        resolved, bound = _interpolate("{{s1.output}}", past)

        assert bound is not None
        assert bound["truncated"] is False
        assert len(resolved.split(", ")) == 50

    def test_no_refs_returns_none(self):
        resolved, bound = _interpolate("plain query with no refs", [])
        assert bound is None
        assert resolved == "plain query with no refs"

    def test_multiple_refs_all_resolved(self):
        past = [
            _make_step_result("s1", [{"text": "alice"}]),
            _make_step_result("s2", [{"text": "bob"}]),
        ]
        resolved, bound = _interpolate("{{s1.output}} and {{s2.output}}", past)

        assert "alice" in resolved
        assert "bob" in resolved
        assert bound is not None
        assert "s1" in bound["refs"]
        assert "s2" in bound["refs"]

    def test_missing_ref_uses_safe_placeholder(self):
        _, bound = _interpolate("{{s99.output}}", [])
        assert bound is not None
        assert "s99" in bound["refs"]
        assert "no output from s99" in bound["refs"]["s99"]

    def test_bound_inputs_records_what_was_substituted(self):
        past = [_make_step_result("s1", [{"text": "apple"}, {"text": "banana"}])]
        _, bound = _interpolate("data: {{s1.output}}", past)
        assert bound is not None
        assert bound["refs"]["s1"] == "apple, banana"


# ---------------------------------------------------------------------------
# Narration (Security Rule 5 — never raw rows)
# ---------------------------------------------------------------------------


class TestNarration:
    def test_empty_chunks_returns_no_results_message(self):
        narration = _narrate([])
        assert "no results" in narration.lower()
        assert len(narration) <= _NARRATION_MAX

    def test_first_3_titles_plus_count(self):
        chunks = [
            {"document_title": "Alpha", "text": "raw1"},
            {"document_title": "Beta", "text": "raw2"},
            {"document_title": "Gamma", "text": "raw3"},
            {"document_title": "Delta", "text": "raw4"},
            {"document_title": "Epsilon", "text": "raw5"},
        ]
        narration = _narrate(chunks)
        assert "5" in narration
        assert "Alpha" in narration
        # 4th+ titles should not appear (only first-3)
        assert "Delta" not in narration
        assert len(narration) <= _NARRATION_MAX

    def test_capped_at_200_chars(self):
        chunks = [{"document_title": "A" * 100, "text": "x"} for _ in range(5)]
        narration = _narrate(chunks)
        assert len(narration) <= _NARRATION_MAX

    def test_no_titles_returns_count_only(self):
        chunks = [{"text": "data", "source_name": None, "document_title": None} for _ in range(3)]
        narration = _narrate(chunks)
        assert "3" in narration or "result" in narration.lower()
        assert len(narration) <= _NARRATION_MAX

    def test_source_name_used_as_fallback_label(self):
        chunks = [{"source_name": "orders.csv", "document_title": None, "text": "row data"}]
        narration = _narrate(chunks)
        assert "orders.csv" in narration


# ---------------------------------------------------------------------------
# Permission re-check (FR-009)
# ---------------------------------------------------------------------------


class TestPermissionRecheck:
    @pytest.mark.asyncio
    async def test_inaccessible_source_fails_without_naming_it(self):
        state = _make_state(
            source_ids=["allowed-src"],
            current_step=_make_plan_step("s1", "evil-src"),
            plan=[_make_plan_step("s1", "evil-src")],
        )
        result = await execute_step(
            state,
            langfuse=_mock_langfuse(),
            embedding_service_factory=AsyncMock(),
            chunk_repository=AsyncMock(),
            db_session=AsyncMock(),
        )

        # No top-level error key — step failure goes into the StepResult
        assert result.get("error") is None

        events = result.get("step_event_data", [])
        fail_event = next((e for e in events if e["state"] == "failed"), None)
        assert fail_event is not None, "expected a 'failed' step event"
        # Must NOT leak the inaccessible source ID
        summary = fail_event.get("summary") or ""
        assert "evil-src" not in summary

        past = result.get("past_steps", [])
        assert len(past) >= 1
        assert past[-1]["verification"]["verdict"] == "unacceptable"

    @pytest.mark.asyncio
    async def test_accessible_source_proceeds_to_finished(self):
        chunk_orm = _make_chunk_orm("c1", "some text")
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([(chunk_orm, 0.2)])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        events = result.get("step_event_data", [])
        assert any(e["state"] == "started" for e in events), "missing 'started' event"
        assert any(e["state"] == "finished" for e in events), "missing 'finished' event"
        past = result.get("past_steps", [])
        assert len(past) == 1
        assert past[0]["step_id"] == "s1"

    @pytest.mark.asyncio
    async def test_retrieval_failure_emits_failed_event(self):
        factory = _mock_embedding_factory()
        repo = AsyncMock()
        repo.similarity_search.side_effect = RuntimeError("db down")

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        events = result.get("step_event_data", [])
        assert any(e["state"] == "failed" for e in events), "expected 'failed' event on error"


# ---------------------------------------------------------------------------
# Step event contract shape
# ---------------------------------------------------------------------------


class TestStepEvents:
    @pytest.mark.asyncio
    async def test_started_event_shape(self):
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        events = result["step_event_data"]
        started = next(e for e in events if e["state"] == "started")
        assert started["step_id"] == "s1"
        assert started["role"] == "executor"
        assert started["summary"] is None
        assert "progress" in started
        assert started["progress"]["current"] == 1
        assert started["progress"]["total"] == 1

    @pytest.mark.asyncio
    async def test_finished_event_has_narration_not_raw_rows(self):
        chunk_orm = _make_chunk_orm("c1", "raw row data that must not appear")
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([(chunk_orm, 0.2)])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        events = result["step_event_data"]
        finished = next(e for e in events if e["state"] == "finished")
        summary = finished["summary"]
        assert summary is not None
        assert len(summary) <= 200
        # Raw chunk text must NOT appear in narration (Security Rule 5)
        assert "raw row data that must not appear" not in summary

    @pytest.mark.asyncio
    async def test_progress_reflects_plan_position(self):
        plan = [
            _make_plan_step("s1", "src-1"),
            _make_plan_step("s2", "src-1"),
            _make_plan_step("s3", "src-1"),
        ]
        state = _make_state(
            source_ids=["src-1"],
            plan=plan,
            current_step=_make_plan_step("s2", "src-1"),
        )
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                state,
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        events = result["step_event_data"]
        started = next(e for e in events if e["state"] == "started")
        assert started["progress"]["current"] == 2
        assert started["progress"]["total"] == 3

    @pytest.mark.asyncio
    async def test_token_delta_keys_present(self):
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        assert "total_input_tokens" in result
        assert "total_output_tokens" in result
        assert isinstance(result["total_input_tokens"], int)
        assert isinstance(result["total_output_tokens"], int)

    @pytest.mark.asyncio
    async def test_output_chunks_not_written_to_retrieved_chunks(self):
        chunk_orm = _make_chunk_orm("c1", "some text")
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([(chunk_orm, 0.2)])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                _make_state(),
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        # Must NOT write to retrieved_chunks (that's the turn-wide synthesizer field)
        assert "retrieved_chunks" not in result
        # Output goes into StepResult.output_chunks
        past = result["past_steps"]
        assert past[-1]["output_chunks"] != []

    @pytest.mark.asyncio
    async def test_past_steps_appended_not_replaced(self):
        existing_result = _make_step_result("s0", [])
        state = _make_state(past_steps=[existing_result])
        factory = _mock_embedding_factory()
        repo = _mock_chunk_repo([])

        with patch(
            "src.agent.nodes.executor.load_schema_context_chunks",
            new_callable=AsyncMock,
        ) as mock_lsc:
            mock_lsc.return_value = []
            result = await execute_step(
                state,
                langfuse=_mock_langfuse(),
                embedding_service_factory=factory,
                chunk_repository=repo,
                db_session=AsyncMock(),
            )

        past = result["past_steps"]
        assert len(past) == 2  # existing + new
        assert past[0]["step_id"] == "s0"
        assert past[1]["step_id"] == "s1"
