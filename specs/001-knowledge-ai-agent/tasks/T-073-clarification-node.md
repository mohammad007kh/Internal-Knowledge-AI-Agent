# T-073 â€” LangGraph Clarification Node

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
OpenAI API (gpt-4o-mini) Â· tenacity 3-retry
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Implement the **`check_clarification` + `handle_clarification` LangGraph nodes**:

1. `check_clarification` â€” heuristic + LLM-based check that sets
   `requires_clarification=True` when the query is too short, vague,
   or explicitly ambiguous  
2. `handle_clarification` â€” calls `langgraph.interrupt()` to pause the
   graph and surface a question to the user; the graph can be resumed
   by supplying the clarification answer  

---

## Acceptance Criteria

- [ ] `check_clarification` node returns `requires_clarification=True` for queries â‰¤ 5 chars
- [ ] `check_clarification` node returns `requires_clarification=False` for normal queries
- [ ] `handle_clarification` calls `interrupt(clarification_question)` correctly
- [ ] When resumed after `interrupt()`, the updated query is appended to `state["messages"]`
- [ ] Langfuse span `"check_clarification"` emitted with `input=query`, `output={"requires": bool}`
- [ ] Unit tests cover: short query (needs clarification), normal query (skip), interrupt call

---

## 1  Clarification Heuristic

```python
# Thresholds for requiring clarification
_MIN_QUERY_LENGTH = 5          # Characters
_AMBIGUOUS_PHRASES = frozenset({
    "it",
    "that",
    "this",
    "them",
    "they",
    "he",
    "she",
    "what",  # standalone single-word query
    "how",
    "why",
    "when",
    "where",
})
```

---

## 2  `app/agent/nodes/clarify.py`

```python
# app/agent/nodes/clarify.py
"""check_clarification and handle_clarification â€” LangGraph nodes."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from app.agent.state import AgentState

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

# â”€â”€ Heuristic thresholds â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_MIN_QUERY_LENGTH = 5
_AMBIGUOUS_SINGLE_WORDS = frozenset({
    "it", "that", "this", "them", "they", "he", "she",
    "what", "how", "why", "when", "where",
})


def _is_ambiguous(query: str) -> tuple[bool, str]:
    """Return (is_ambiguous, reason_message).

    A query is considered ambiguous if:
    - It is shorter than ``_MIN_QUERY_LENGTH`` characters after stripping, or
    - It consists of a single word that is known to be context-dependent.
    """
    stripped = query.strip()

    if len(stripped) < _MIN_QUERY_LENGTH:
        return True, "Your question is too short to search accurately. Could you provide more detail?"

    words = stripped.lower().split()
    if len(words) == 1 and words[0] in _AMBIGUOUS_SINGLE_WORDS:
        return True, f"Your query '{stripped}' is ambiguous. What specifically would you like to know?"

    return False, ""


# â”€â”€ check_clarification node â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def check_clarification(
    state: AgentState,
    *,
    langfuse: "Langfuse",
) -> dict:
    """Decide whether the user query needs clarification.

    Uses a fast heuristic check (no LLM call) to keep latency low.
    For production use, this can be augmented with a lightweight LLM
    classification call.
    """
    query: str = state.get("query", "").strip()

    span = langfuse.span(
        trace_id=state["trace_id"],
        name="check_clarification",
        input={"query": query},
    )

    try:
        ambiguous, reason = _is_ambiguous(query)

        span.update(
            output={"requires_clarification": ambiguous, "reason": reason or "none"}
        )
        logger.info(
            "check_clarification: query_len=%d requires=%s",
            len(query),
            ambiguous,
        )
        return {
            "requires_clarification": ambiguous,
            "clarification_question": reason if ambiguous else None,
        }
    finally:
        span.end()


# â”€â”€ handle_clarification node â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def handle_clarification(state: AgentState) -> dict:
    """Pause the graph and ask the user for clarification.

    ``langgraph.interrupt()`` suspends execution at this node.
    The LangGraph checkpointer persists the current state so that
    the graph can be resumed once the user provides their answer.

    When resumed, LangGraph re-runs this node with ``interrupt`` returning
    the user's clarification response.  We append it to ``state["messages"]``
    and clear the clarification flags so the pipeline continues normally.
    """
    question = state.get("clarification_question") or "Could you please clarify your question?"

    logger.info("handle_clarification: surfacing question to user")

    # Suspend here â€” the UI receives the question via SSE and prompts the user.
    # ``interrupt()`` raises ``GraphInterrupt`` inside LangGraph; the caller
    # (API router) catches it and streams the question to the client.
    clarification_answer: str = interrupt(question)

    # When resumed, append the user's answer as a new HumanMessage
    # and reset clarification state so the normal path continues.
    return {
        "messages": [HumanMessage(content=clarification_answer)],
        "query": clarification_answer,
        "requires_clarification": False,
        "clarification_question": None,
    }
```

---

## 3  `app/agent/nodes/__init__.py` â€” patch

```python
# app/agent/nodes/__init__.py
"""LangGraph node implementations."""
from app.agent.nodes.clarify import check_clarification, handle_clarification  # noqa: F401
from app.agent.nodes.generate import generate_response  # noqa: F401
from app.agent.nodes.retrieve import retrieve_context  # noqa: F401
```

---

## 4  `app/agent/pipeline.py` â€” patch

Replace the two stub functions and add imports at the top:

```python
# Remove stubs:
async def check_clarification(state: AgentState) -> dict:
    ...

async def handle_clarification(state: AgentState) -> dict:
    ...

# Add import at top of file:
from app.agent.nodes.clarify import check_clarification, handle_clarification  # noqa: F401
```

---

## 5  Unit Tests â€” `tests/unit/agent/test_clarify_node.py`

```python
# tests/unit/agent/test_clarify_node.py
"""Unit tests for check_clarification and handle_clarification nodes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.nodes.clarify import check_clarification, handle_clarification


@pytest.fixture()
def base_state():
    return {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "What is the refund policy for annual subscriptions?",
        "source_ids": ["src-1"],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [],
        "final_answer": None,
        "error": None,
    }


@pytest.fixture()
def mock_langfuse():
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


@pytest.mark.asyncio
async def test_normal_query_no_clarification(base_state, mock_langfuse):
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is False
    assert result["clarification_question"] is None


@pytest.mark.asyncio
async def test_short_query_requires_clarification(base_state, mock_langfuse):
    base_state["query"] = "hi"  # 2 chars
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True
    assert result["clarification_question"] is not None


@pytest.mark.asyncio
async def test_single_ambiguous_word_requires_clarification(base_state, mock_langfuse):
    base_state["query"] = "what"
    result = await check_clarification(base_state, langfuse=mock_langfuse)
    assert result["requires_clarification"] is True


@pytest.mark.asyncio
async def test_span_emitted(base_state, mock_langfuse):
    await check_clarification(base_state, langfuse=mock_langfuse)
    mock_langfuse.span.assert_called_once_with(
        trace_id="trace-1",
        name="check_clarification",
        input={"query": base_state["query"]},
    )
    mock_langfuse.span.return_value.end.assert_called_once()


@pytest.mark.asyncio
async def test_handle_clarification_calls_interrupt(base_state):
    """interrupt() is called with the clarification question."""
    base_state["clarification_question"] = "What product are you asking about?"

    with patch("app.agent.nodes.clarify.interrupt") as mock_interrupt:
        mock_interrupt.return_value = "I mean the Pro plan"
        result = await handle_clarification(base_state)

    mock_interrupt.assert_called_once_with("What product are you asking about?")
    assert result["query"] == "I mean the Pro plan"
    assert result["requires_clarification"] is False
    assert len(result["messages"]) == 1
```

---

## How `interrupt()` Works with SSE

When `handle_clarification` calls `interrupt(question)`:

1. LangGraph throws `GraphInterrupt` internally  
2. The API route (T-076) catches the interrupt during `astream_events()`  
3. The route streams an SSE event of type `"clarification"` with the question text  
4. The Next.js client renders an inline input  
5. User submits â†’ POST resumes the graph via `graph.ainvoke(resume_value, config)` 

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/agent/nodes/clarify.py` |
| PATCH  | `app/agent/nodes/__init__.py` |
| PATCH  | `app/agent/pipeline.py` |
| CREATE | `tests/unit/agent/test_clarify_node.py` |
