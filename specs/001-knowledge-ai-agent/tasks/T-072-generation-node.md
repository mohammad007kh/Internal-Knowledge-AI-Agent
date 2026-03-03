# T-072 â€” LangGraph Generation Node

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
OpenAI API (gpt-4o-mini) Â· tenacity 3-retry
RFC 7807 Problem Details â€” all non-2xx API responses
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
FR-020: connection strings MUST NEVER appear in LLM output or logs
```

## Goal
Implement the **`generate_response` LangGraph node** that:

1. Assembles a prompt from `state["retrieved_chunks"]` + `state["messages"]`  
2. Calls the OpenAI chat completion API (`gpt-4o-mini`)  
3. Emits a Langfuse span including model name + token usage  
4. Sets `state["final_answer"]` with the raw LLM text  

---

## Acceptance Criteria

- [ ] `generate_response` node sets `state["final_answer"]` as a non-empty string
- [ ] System prompt is rendered with retrieved chunk texts
- [ ] `model="gpt-4o-mini"`, `temperature=0.2`, `max_tokens=1024`
- [ ] Langfuse span `"generate_response"` contains `usage.input_tokens` + `usage.output_tokens`
- [ ] If OpenAI call fails after 3 retries, node sets `state["error"]` and returns empty answer
- [ ] Unit test: mock `AsyncOpenAI` â†’ assert `final_answer` is populated

---

## 1  `app/agent/prompts.py`

```python
# app/agent/prompts.py
"""Prompt templates for the LangGraph pipeline."""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a helpful AI assistant for an internal knowledge base.
Your task is to answer the user's question using ONLY the context provided below.
If the context does not contain enough information to answer the question,
say "I don't have enough information in the knowledge base to answer that."

Do NOT reveal connection strings, credentials, or internal system details.

## Retrieved Context
{context}
"""

CLARIFICATION_PROMPT = """\
The user's question is ambiguous. Politely ask for the specific clarification
needed to retrieve the correct information.
Clarification needed: {clarification_question}
"""

NO_CONTEXT_MESSAGE = (
    "I don't have enough information in the knowledge base to answer that. "
    "Please ensure relevant sources have been synced and you have access to them."
)


def render_system_prompt(chunks: list[dict]) -> str:
    """Render the system prompt with deduped chunk texts."""
    if not chunks:
        context_text = "(No relevant context found)"
    else:
        seen: set[str] = set()
        parts: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            text = chunk.get("text", "").strip()
            if text and text not in seen:
                seen.add(text)
                parts.append(f"[{i}] {text}")
        context_text = "\n\n".join(parts) if parts else "(No relevant context found)"

    return SYSTEM_PROMPT.format(context=context_text)
```

---

## 2  `app/agent/nodes/generate.py`

```python
# app/agent/nodes/generate.py
"""generate_response â€” LangGraph node."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import tenacity
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import AsyncOpenAI, APIStatusError, APITimeoutError

from app.agent.prompts import NO_CONTEXT_MESSAGE, render_system_prompt
from app.agent.state import AgentState

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_TEMPERATURE = 0.2
_MAX_TOKENS = 1024
_MAX_RETRIES = 3


def _build_messages(state: AgentState) -> list[dict]:
    """Convert LangGraph state messages to OpenAI chat format."""
    system_text = render_system_prompt(state.get("retrieved_chunks", []))
    result = [{"role": "system", "content": system_text}]

    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, SystemMessage):
            pass  # already prepended as system

    return result


async def generate_response(
    state: AgentState,
    *,
    openai_client: AsyncOpenAI,
    langfuse: "Langfuse",
) -> dict:
    """Run the LLM and set state["final_answer"].

    Retries up to 3 times on transient OpenAI errors (429, 5xx, timeout).
    On permanent failure sets ``state["error"]`` and returns an
    empty-context fallback message.
    """
    span = langfuse.span(
        trace_id=state["trace_id"],
        name="generate_response",
        input={
            "model": _MODEL,
            "chunk_count": len(state.get("retrieved_chunks", [])),
            "query": state.get("query", "")[:200],  # truncate for tracing
        },
    )

    messages = _build_messages(state)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(_MAX_RETRIES),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=8),
        retry=tenacity.retry_if_exception_type((APIStatusError, APITimeoutError)),
        reraise=True,
    )
    async def _call() -> tuple[str, dict]:
        response = await openai_client.chat.completions.create(
            model=_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
        )
        text = response.choices[0].message.content or ""
        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        return text, usage

    try:
        answer, usage = await _call()
        span.update(output={"answer_length": len(answer), **usage})
        logger.info(
            "generate_response: tokens in=%d out=%d",
            usage["input_tokens"],
            usage["output_tokens"],
        )
        return {"final_answer": answer}

    except Exception as exc:
        logger.exception("generate_response failed after retries: %s", exc)
        span.update(output={"error": str(exc)[:200]})
        return {
            "final_answer": NO_CONTEXT_MESSAGE,
            "error": "generation_failed",
        }
    finally:
        span.end()
```

---

## 3  `app/agent/nodes/__init__.py` â€” patch

```python
# app/agent/nodes/__init__.py
"""LangGraph node implementations."""
from app.agent.nodes.generate import generate_response  # noqa: F401
from app.agent.nodes.retrieve import retrieve_context  # noqa: F401
```

---

## 4  `app/agent/pipeline.py` â€” patch

Replace the stub `generate_response` definition and add import:

```python
# Remove stub:
async def generate_response(state: AgentState) -> dict:
    """Call LLM with retrieved context and produce a raw response."""
    logger.debug("node=generate_response")
    return {}

# Add at top of file with other imports:
from app.agent.nodes.generate import generate_response  # noqa: F401
```

---

## 5  Unit Tests â€” `tests/unit/agent/test_generate_node.py`

```python
# tests/unit/agent/test_generate_node.py
"""Unit tests for the generate_response LangGraph node."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.agent.nodes.generate import generate_response


@pytest.fixture()
def base_state():
    return {
        "session_id": "sess-1",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "query": "What is our refund policy?",
        "source_ids": ["src-1"],
        "retrieved_chunks": [
            {"chunk_id": "c1", "source_id": "src-1", "text": "Refunds within 30 days.", "score": 0.1}
        ],
        "requires_clarification": False,
        "clarification_question": None,
        "messages": [HumanMessage(content="What is our refund policy?")],
        "final_answer": None,
        "error": None,
    }


@pytest.fixture()
def mock_openai_client():
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "You can get a refund within 30 days."
    completion.usage.prompt_tokens = 100
    completion.usage.completion_tokens = 25
    client.chat.completions.create.return_value = completion
    return client


@pytest.fixture()
def mock_langfuse():
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


@pytest.mark.asyncio
async def test_sets_final_answer(base_state, mock_openai_client, mock_langfuse):
    result = await generate_response(
        base_state,
        openai_client=mock_openai_client,
        langfuse=mock_langfuse,
    )
    assert result["final_answer"] == "You can get a refund within 30 days."
    assert "error" not in result or result["error"] is None


@pytest.mark.asyncio
async def test_span_emitted(base_state, mock_openai_client, mock_langfuse):
    await generate_response(
        base_state,
        openai_client=mock_openai_client,
        langfuse=mock_langfuse,
    )
    mock_langfuse.span.assert_called_once()
    span = mock_langfuse.span.return_value
    span.end.assert_called_once()


@pytest.mark.asyncio
async def test_openai_failure_returns_fallback(base_state, mock_langfuse):
    from openai import APIStatusError  # noqa: PLC0415

    failing_client = AsyncMock()
    failing_client.chat.completions.create.side_effect = APIStatusError(
        "rate limit", response=MagicMock(status_code=429), body={}
    )

    result = await generate_response(
        base_state,
        openai_client=failing_client,
        langfuse=mock_langfuse,
    )
    assert result["error"] == "generation_failed"
    assert "knowledge base" in result["final_answer"]


@pytest.mark.asyncio
async def test_no_context_uses_fallback_message(base_state, mock_openai_client, mock_langfuse):
    """With no retrieved chunks still calls LLM â€” fallback text injected into prompt."""
    base_state["retrieved_chunks"] = []
    result = await generate_response(
        base_state,
        openai_client=mock_openai_client,
        langfuse=mock_langfuse,
    )
    # still calls OpenAI (prompt will contain "No relevant context found")
    assert mock_openai_client.chat.completions.create.called
    assert result.get("final_answer") is not None
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/agent/prompts.py` |
| CREATE | `app/agent/nodes/generate.py` |
| PATCH  | `app/agent/nodes/__init__.py` |
| PATCH  | `app/agent/pipeline.py` |
| CREATE | `tests/unit/agent/test_generate_node.py` |
