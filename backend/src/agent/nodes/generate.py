# src/agent/nodes/generate.py
"""generate_response — LangGraph node.

Resolves the AI model record at node entry via :class:`AIModelResolver`,
so admin updates to ``/admin/ai-models`` and ``/admin/llm-settings`` take
effect on the next request after the resolver's TTL window (60 s by default).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import tenacity
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import APIStatusError, APITimeoutError

from src.agent.prompts import NO_CONTEXT_MESSAGE, render_system_prompt
from src.agent.state import AgentState

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "generate_response"
_MAX_RETRIES = 3


def _build_messages(state: AgentState, custom_prompt: str | None) -> list[dict]:  # type: ignore[type-arg]
    """Convert LangGraph state messages to OpenAI chat format."""
    if custom_prompt:
        system_text = custom_prompt
    else:
        system_text = render_system_prompt(state.get("retrieved_chunks", []))
    result = [{"role": "system", "content": system_text}]

    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": str(msg.content)})
        elif isinstance(msg, SystemMessage):
            pass  # already prepended as system

    return result


async def generate_response(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    langfuse: Langfuse,
) -> dict:  # type: ignore[type-arg]
    """Run the LLM and set state["final_answer"].

    Retries up to 3 times on transient OpenAI errors (429, 5xx, timeout).
    On permanent failure sets ``state["error"]`` and returns an
    empty-context fallback message.
    """
    client = await ai_model_resolver.resolve(_STAGE)

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={
            "model": client.model_id,
            "provider": client.provider,
            "chunk_count": len(state.get("retrieved_chunks", [])),
            "query": state.get("query", "")[:200],
        },
    )

    messages = _build_messages(state, client.custom_prompt)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(_MAX_RETRIES),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=8),
        retry=tenacity.retry_if_exception_type((APIStatusError, APITimeoutError)),
        reraise=True,
    )
    async def _call() -> tuple[str, dict]:  # type: ignore[type-arg]
        response = await client.http_client.chat.completions.create(
            model=client.model_id,
            messages=messages,  # type: ignore[arg-type]
            temperature=client.temperature,
            max_tokens=client.max_tokens,
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
            "generate_response: model=%s tokens in=%d out=%d",
            client.model_id,
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
