# src/agent/nodes/generate.py
"""generate_response — LangGraph node.

Resolves the AI model record at node entry via :class:`AIModelResolver`,
so admin updates to ``/admin/ai-models`` and ``/admin/llm-settings`` take
effect on the next request after the resolver's TTL window (60 s by default).

The node calls a LangChain :class:`BaseChatModel` runnable rather than the
``AsyncOpenAI`` client directly so that LangGraph's
``astream_events(version="v2")`` surfaces real ``on_chat_model_stream``
events to :mod:`src.services.chat_stream_service`.  The chat model is
tagged with ``run_name="synthesizer"`` so Langfuse spans and
``astream_events`` output match the seeded slot name used by the admin
overrides on ``/admin/llm-settings``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import tenacity
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from openai import APIStatusError, APITimeoutError

from src.agent.prompts import NO_CONTEXT_MESSAGE, render_system_prompt
from src.agent.state import AgentState
from src.services.ai_model_resolver import build_chat_model

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelClient, AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "synthesizer"
_MAX_RETRIES = 3


def _build_messages(
    state: AgentState, custom_prompt: str | None
) -> list[BaseMessage]:
    """Convert LangGraph state messages to LangChain ``BaseMessage`` list.

    The system prompt is either the admin-supplied ``custom_prompt`` from
    ``LLMConfiguration`` (when set) or the default rendered from the
    retrieved chunks.  Caller-supplied ``SystemMessage`` instances are
    dropped — the agent owns the system prompt.
    """
    if custom_prompt:
        system_text = custom_prompt
    else:
        system_text = render_system_prompt(state.get("retrieved_chunks", []))
    result: list[BaseMessage] = [SystemMessage(content=system_text)]

    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            result.append(HumanMessage(content=str(msg.content)))
        elif isinstance(msg, AIMessage):
            result.append(AIMessage(content=str(msg.content)))
        elif isinstance(msg, SystemMessage):
            pass  # already prepended as system

    return result


async def generate_response(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    langfuse: Langfuse,
    chat_model_factory: Any = None,
) -> dict:  # type: ignore[type-arg]
    """Run the LLM and set state["final_answer"].

    Retries up to 3 times on transient OpenAI errors (429, 5xx, timeout).
    On permanent failure sets ``state["error"]`` and returns an
    empty-context fallback message.

    The ``chat_model_factory`` parameter exists so callers can inject a
    :class:`langchain_core.language_models.fake_chat_models.FakeListChatModel`
    (or any other ``BaseChatModel``) in place of :class:`ChatOpenAI`. It
    defaults to ``None`` and is resolved to :func:`build_chat_model` at call
    time — so a test can ``monkeypatch.setattr("src.agent.nodes.generate.
    build_chat_model", ...)`` and the patch takes effect even though the
    pipeline graph calls this node without passing the kwarg. (A module-level
    default like ``= build_chat_model`` would be bound at def-time and ignore
    the patch.)
    """
    if chat_model_factory is None:
        chat_model_factory = build_chat_model
    client: AIModelClient = await ai_model_resolver.resolve(_STAGE)

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={
            "model": client.model_id,
            "provider": client.provider,
            "chunk_count": len(state.get("retrieved_chunks", [])),
            "query": state.get("query", "")[:200],
            # Estimate-then-reconcile (FR-021): record configured max_tokens as
            # the pre-call output budget estimate; actuals replace it post-stream.
            "estimated_output_tokens": client.max_tokens,
        },
    )

    messages = _build_messages(state, client.custom_prompt)

    try:
        chat_model = chat_model_factory(client).with_config(
            {"run_name": _STAGE, "tags": [_STAGE]}
        )
    except Exception as exc:
        # Bad provider config / missing key / unsupported model — the
        # build itself raised. Span has already been started above; close
        # it here and surface the canned fallback so the request still
        # responds.
        logger.exception("generate_response: chat_model build failed: %s", exc)
        span.update(output={"error": f"build_failed: {str(exc)[:200]}"})
        span.end()
        return {
            "final_answer": NO_CONTEXT_MESSAGE,
            "error": "generation_failed",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    # Once the first token has streamed to the client, we MUST NOT retry —
    # tenacity replays from token 0 and the SSE consumer cannot recall
    # the deltas it has already forwarded, so the user would see duplicated
    # text. The closure flag plus the custom retry predicate enforces:
    # retry transient errors only when nothing has been emitted yet.
    chunks_emitted = {"any": False}

    def _retry_predicate(retry_state: tenacity.RetryCallState) -> bool:
        if chunks_emitted["any"]:
            return False
        outcome = retry_state.outcome
        if outcome is None or not outcome.failed:
            return False
        return isinstance(outcome.exception(), (APIStatusError, APITimeoutError))

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(_MAX_RETRIES),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=8),
        retry=_retry_predicate,
        reraise=True,
    )
    async def _call() -> tuple[str, dict]:  # type: ignore[type-arg]
        # ``astream`` (rather than ``ainvoke``) guarantees the chat
        # model's ``_astream`` is exercised, so LangGraph's astream_events
        # surfaces ``on_chat_model_stream`` events with per-token chunks
        # to the SSE consumer.  We accumulate the chunks here so the node
        # still returns the full answer in its dict patch — the streaming
        # is purely additive on top.
        parts: list[str] = []
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        async for chunk in chat_model.astream(messages):
            content = getattr(chunk, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
                chunks_emitted["any"] = True
            # ``AIMessageChunk.usage_metadata`` arrives on the final chunk
            # for providers that report it (OpenAI does when ``stream_options
            # = {"include_usage": True}`` is set; ``ChatOpenAI`` toggles
            # that automatically when ``streaming=True``).
            usage_meta = getattr(chunk, "usage_metadata", None) or {}
            if usage_meta:
                usage["input_tokens"] = int(
                    usage_meta.get("input_tokens") or usage["input_tokens"]
                )
                usage["output_tokens"] = int(
                    usage_meta.get("output_tokens") or usage["output_tokens"]
                )
        return "".join(parts), usage

    try:
        answer, usage = await _call()
        in_tok = usage["input_tokens"]
        out_tok = usage["output_tokens"]
        span.update(output={"answer_length": len(answer), **usage})
        logger.info(
            "generate_response: model=%s tokens in=%d out=%d",
            client.model_id,
            in_tok,
            out_tok,
        )
        # Emit accumulated turn cost as a Langfuse score (Constitution II).
        prior_in = state.get("total_input_tokens") or 0
        prior_out = state.get("total_output_tokens") or 0
        langfuse.score(  # type: ignore[attr-defined]
            trace_id=state["trace_id"],
            name="turn_token_cost",
            value=float(prior_in + prior_out + in_tok + out_tok),
        )
        return {
            "final_answer": answer,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    except Exception as exc:
        logger.exception("generate_response failed after retries: %s", exc)
        span.update(output={"error": str(exc)[:200]})
        return {
            "final_answer": NO_CONTEXT_MESSAGE,
            "error": "generation_failed",
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
    finally:
        span.end()
