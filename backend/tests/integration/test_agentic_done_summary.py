"""Integration smoke for T-058: a 1-step agentic turn emits + persists a
compact ``activity_summary`` on the ``done`` SSE event (FR-018 / FR-021).

Drives the REAL agentic graph (``build_pipeline(sandbox=True)`` with
``PIPELINE_AGENTIC_ENABLED`` forced on) end-to-end through
``run_pipeline_stream``:

* planner LLM returns a single-step plan against the permitted source;
* execute_step retrieves one (mocked) chunk;
* verify_step (light path) grades it ``acceptable`` → route ``synthesize``;
* the synthesizer (a ``FakeListChatModel``) streams the final answer.

Asserts the terminal ``done`` frame carries a NON-NULL ``activity_summary`` of
the compact shape (data-model §3), AND that the persistence callback received
the same summary (the dict that lands on ``chat_messages.activity_summary``).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    FakeListChatModel,
)

from src.agent import pipeline as pipeline_mod  # noqa: E402
from src.agent.pipeline import build_agent_budget_snapshot, build_pipeline  # noqa: E402
from src.services.ai_model_resolver import AIModelClient  # noqa: E402
from src.services.chat_stream_service import run_pipeline_stream  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in frames:
        m = re.match(r"^event: (\S+)\ndata: (.+)\n\n$", raw, flags=re.DOTALL)
        assert m, f"Frame does not match SSE shape: {raw!r}"
        out.append((m.group(1), json.loads(m.group(2))))
    return out


def _client_returning(payload: dict | str) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = (
        payload if isinstance(payload, str) else json.dumps(payload)
    )
    completion.usage.prompt_tokens = 60
    completion.usage.completion_tokens = 12
    client.chat.completions.create.return_value = completion
    return client


def _make_resolver(stage_clients: dict[str, AsyncMock]) -> AsyncMock:
    resolver = AsyncMock()

    async def _resolve(stage: str) -> AIModelClient:
        http_client = stage_clients.get(stage) or _client_returning("ok")
        return AIModelClient(
            ai_model_id=uuid.uuid4(),
            provider="openai",
            model_id="gpt-4o-mini",
            temperature=0.0,
            max_tokens=1024,
            custom_prompt=None,
            capabilities={},
            http_client=http_client,
        )

    resolver.resolve.side_effect = _resolve
    return resolver


def _make_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = "trace-agentic-1"
    return t


@pytest.fixture
def _force_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_AGENTIC_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_V2_ENABLED", True)
    monkeypatch.setattr(pipeline_mod.settings, "PIPELINE_REFLECTOR_ENABLED", False)


def _build_one_step_pipeline(monkeypatch: pytest.MonkeyPatch, *, source_id: uuid.UUID):
    """Build the real agentic graph wired for a single successful step."""
    # planner → 1-step plan; retrieval_grader → acceptable; synthesizer streams.
    plan_payload = {
        "decision": "plan",
        "steps": [
            {
                "id": "s1",
                "label": "Find the refund policy",
                "source_id": str(source_id),
                "sub_query": "refund policy",
                "depends_on": [],
            }
        ],
    }
    grader_payload = {"verdict": "acceptable", "reason": "fully answers the sub-query", "checks": {}}
    resolver = _make_resolver(
        {
            "planner": _client_returning(plan_payload),
            "retrieval_grader": _client_returning(grader_payload),
            # synthesizer goes through build_chat_model (patched below), not the
            # raw http_client, so its stage client is irrelevant here.
        }
    )

    # Planner/replan source_meta_loader hits SourceRepository.list_by_ids.
    src = MagicMock()
    src.id = source_id
    src.name = "Docs"
    src.purpose = "Policy documentation."
    src.example_questions = ["What is the refund policy?"]
    src.out_of_scope = ["PII"]
    source_repo = AsyncMock()
    source_repo.list_by_ids.return_value = [src]

    # Retrieval: one matching chunk for the executor.
    embedding = AsyncMock()
    embedding.embed_query.return_value = [0.1] * 1536
    factory = AsyncMock()
    factory.for_active.return_value = (embedding, uuid.uuid4())

    fake_chunk = MagicMock()
    fake_chunk.id = "chunk-1"
    fake_chunk.source_id = str(source_id)
    fake_chunk.chunk_text = "Refunds are processed within 30 days."
    fake_chunk.metadata_ = {
        "document_title": "Refund.pdf",
        "page_number": 1,
        "source_name": "Docs",
    }
    chunk_repo = AsyncMock()
    chunk_repo.similarity_search.return_value = [(fake_chunk, 0.05)]

    # Executor loads step-scoped schema context — stub to empty so retrieval is
    # the only chunk producer (DB sources only; this is a doc source).
    async def _no_schema(*_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "src.agent.nodes.executor.load_schema_context_chunks", _no_schema
    )

    # Synthesizer: a real FakeListChatModel so astream_events fires on_chat_model_stream.
    answer = "Refunds are available within 30 days."
    monkeypatch.setattr(
        "src.agent.nodes.generate.build_chat_model",
        lambda _client: FakeListChatModel(responses=[answer]),
    )

    chat_session_repo = AsyncMock()
    chat_msg_repo = AsyncMock()
    langfuse = MagicMock()
    langfuse.span.return_value = MagicMock()

    pipeline = build_pipeline(
        db_session=AsyncMock(),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_msg_repo,
        ai_model_resolver=resolver,
        embedding_service_factory=factory,
        langfuse=langfuse,
        guardrail_service=None,  # keep the graph minimal for the smoke
        source_repository=source_repo,
        sandbox=True,
    )
    return pipeline, answer


def _initial_state(source_id: uuid.UUID, query: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=query)],
        "source_ids": [str(source_id)],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": str(uuid.uuid4()),
        "user_id": "user-1",
        "trace_id": "trace-agentic-1",
        "query": query,
        "final_answer": None,
        "error": None,
        "sources": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "raw_user_intent": query,
        "plan": [],
        "past_steps": [],
        "current_step": None,
        "plan_revision": 0,
        "budget": build_agent_budget_snapshot(),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_step_turn_emits_activity_summary(
    monkeypatch: pytest.MonkeyPatch, _force_agentic: None
) -> None:
    source_id = uuid.uuid4()
    pipeline, answer = _build_one_step_pipeline(monkeypatch, source_id=source_id)
    state = _initial_state(source_id, "What is the refund policy?")

    frames = [
        f
        async for f in run_pipeline_stream(
            pipeline=pipeline,
            initial_state=state,
            config={"configurable": {"thread_id": state["session_id"]}},
            trace_id="trace-agentic-1",
            session_id=state["session_id"],
            langfuse_tracing=_make_tracing(),
            persist_assistant=False,
            on_done=None,
        )
    ]
    parsed = _parse_sse_frames(frames)
    events = [name for name, _ in parsed]
    assert events[-1] == "done"

    done_payload = parsed[-1][1]
    summary = done_payload.get("activity_summary")
    assert summary is not None, "done event must carry a non-null activity_summary"

    # Compact shape (data-model §3).
    for key in (
        "step_count",
        "source_count",
        "had_replan",
        "had_failure",
        "budget_hit",
        "turn_tokens",
        "cost_label",
        "plan",
        "superseded_plan",
        "revision_reason",
        "roles",
    ):
        assert key in summary, f"missing compact-summary key: {key}"

    assert summary["step_count"] == 1
    assert summary["source_count"] == 1
    assert summary["had_replan"] is False
    assert summary["budget_hit"] is False
    assert summary["superseded_plan"] is None
    assert summary["cost_label"] in ("small", "medium", "large")
    assert isinstance(summary["turn_tokens"], dict)
    assert {"input", "output"} <= set(summary["turn_tokens"])
    # The single plan row reflects the executed step.
    assert summary["plan"][0]["id"] == "s1"
    assert summary["plan"][0]["status"] == "done"
    # roles[].line are capped at 200 chars (security rule 5).
    for role in summary["roles"]:
        assert len(role.get("line", "")) <= 200
    # A planner role + an executor role for s1 are present.
    role_names = {r["role"] for r in summary["roles"]}
    assert "planner" in role_names
    assert "executor" in role_names


@pytest.mark.asyncio
async def test_one_step_turn_persists_activity_summary(
    monkeypatch: pytest.MonkeyPatch, _force_agentic: None
) -> None:
    """The summary passed to ``done`` is the SAME dict handed to the persist callback."""
    source_id = uuid.uuid4()
    pipeline, _ = _build_one_step_pipeline(monkeypatch, source_id=source_id)
    state = _initial_state(source_id, "What is the refund policy?")

    persisted: dict[str, Any] = {}

    async def _on_done(final_answer: str, *, activity_summary: dict | None = None) -> str:
        persisted["answer"] = final_answer
        persisted["activity_summary"] = activity_summary
        return "msg-123"

    frames = [
        f
        async for f in run_pipeline_stream(
            pipeline=pipeline,
            initial_state=state,
            config={"configurable": {"thread_id": state["session_id"]}},
            trace_id="trace-agentic-1",
            session_id=state["session_id"],
            langfuse_tracing=_make_tracing(),
            persist_assistant=True,
            on_done=_on_done,
        )
    ]
    parsed = _parse_sse_frames(frames)
    done_payload = parsed[-1][1]

    # Persisted summary is non-null and identical to the one on the done event.
    assert persisted.get("activity_summary") is not None
    assert persisted["activity_summary"] == done_payload["activity_summary"]
    assert done_payload["message_id"] == "msg-123"
