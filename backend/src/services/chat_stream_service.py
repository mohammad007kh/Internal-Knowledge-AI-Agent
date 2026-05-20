"""Shared streaming core for the chat pipeline.

Both production endpoints (``POST /chat/sessions/{id}/messages`` and
``POST /chat/sandbox/stream``) drive the same LangGraph pipeline and emit
the *same* SSE event grammar so the frontend's :file:`use-chat-stream.ts`
hook is reusable across both. The grammar lives in
:class:`src.schemas.chat.ChatStreamEvent`; this module owns the
"feed-the-events-out, persist-when-asked" loop that wraps it.

The two endpoints diverge on three axes:

1. **Persistence** — session chats save the assistant message to
   ``chat_messages`` and emit a real ``message_id`` in the ``done`` event;
   sandbox runs persist nothing and emit the sentinel ``__sandbox__`` /
   ``""`` pair so the frontend can still close out cleanly.
2. **History** — session chats let :func:`load_history` populate
   ``state["messages"]`` from DB; sandbox runs inject the caller-supplied
   history directly.  ``load_history`` itself short-circuits when
   ``session_id == "__sandbox__"`` (see :mod:`src.agent.nodes.history`).
3. **Langfuse tagging** — sandbox traces are still recorded (the whole
   point is debugging) but tagged ``sandbox=True`` so analytics dashboards
   can exclude them from production funnel metrics.

Keep the SSE grammar **byte-identical** between the two callers: the
frontend hook is tested against one shape; if the sandbox path emits a
slightly different ``done`` payload, the hook will silently fail to close
the loading state.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.schemas.chat import ChatStreamEvent

logger = logging.getLogger(__name__)


SANDBOX_SESSION_ID = "__sandbox__"


def history_to_lc_messages(
    history: list[dict[str, str]] | None,
) -> list[HumanMessage | AIMessage]:
    """Convert wire-format history to LangChain ``BaseMessage`` instances.

    Wire format mirrors OpenAI's: ``[{"role": "user", "content": "…"}, …]``.
    Only ``user`` and ``assistant`` roles are honoured — ``system`` is
    dropped because the production agent injects its own system prompts.
    Caller is expected to cap the list length BEFORE calling (sandbox API
    enforces 20 turns).
    """
    if not history:
        return []
    out: list[HumanMessage | AIMessage] = []
    for item in history:
        role = item.get("role")
        content = item.get("content") or ""
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        # silently drop unknown roles — defensive against future shape drift
    return out


async def run_pipeline_stream(
    *,
    pipeline: Any,
    initial_state: dict[str, Any],
    config: dict[str, Any],
    trace_id: str,
    session_id: str,
    langfuse_tracing: Any,
    persist_assistant: bool,
    on_done: Callable[[str], Awaitable[str]] | None = None,
    pre_yield: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Drive the LangGraph pipeline and yield SSE frames.

    Parameters
    ----------
    pipeline
        The compiled LangGraph pipeline (typically ``Container.pipeline()``).
    initial_state
        Seeded :class:`AgentState`.  The caller is responsible for setting
        ``session_id`` / ``user_id`` / ``query`` / ``source_ids``; this
        function does not mutate the dict.
    config
        ``configurable`` dict for ``pipeline.astream_events``.  Sandbox
        callers should still pass a ``thread_id`` so LangGraph's
        checkpointer doesn't trip — pass the sandbox sentinel session id.
    trace_id
        Langfuse trace id from :meth:`LangfuseTracingService.start_trace`.
    session_id
        SSE-emitted session id.  Pass :data:`SANDBOX_SESSION_ID` for
        sandbox runs so the frontend can branch on it without parsing
        the URL.
    langfuse_tracing
        Service instance — used to ``end_trace`` on every exit path so
        spans are never leaked.
    persist_assistant
        ``True`` for the session-chat path: the caller will save the
        assistant message via ``on_done`` and the returned ``message_id``
        is propagated into the ``done`` event.  ``False`` for the
        sandbox path: ``message_id`` is emitted as ``""`` and ``on_done``
        is not invoked.
    on_done
        Async callback that receives ``final_answer`` and returns the
        persisted ``message_id``.  Required when ``persist_assistant=True``,
        ignored otherwise. Errors raised by the callback are converted to
        an SSE ``error`` frame so the frontend can exit its pending state.
    pre_yield
        Pre-formatted SSE strings to emit BEFORE the pipeline starts (e.g.
        the auto-generated session title). They flow through unchanged.
    """
    try:
        from langgraph.errors import GraphInterrupt  # noqa: PLC0415
    except ImportError:
        GraphInterrupt = None  # type: ignore[assignment,misc]

    if pre_yield:
        for frame in pre_yield:
            yield frame

    final_answer = ""
    streamed_answer = ""  # Tokens already shipped via ``on_chat_model_stream``.
    sources: list[Any] = []

    try:
        async for event in pipeline.astream_events(
            initial_state, config=config, version="v2"
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                token = event.get("data", {}).get("chunk", {})
                if hasattr(token, "content") and token.content:
                    streamed_answer += token.content
                    yield ChatStreamEvent.delta(token.content).to_sse()
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                output = event.get("data", {}).get("output", {})
                final_answer = output.get("final_answer", final_answer)
                sources = output.get("sources", sources)
        # If the synthesizer streamed real tokens, prefer the streamed
        # text — it's the canonical source of truth for what the user
        # actually saw on-wire.  Falling back to the LangGraph
        # ``on_chain_end`` output covers stages that bypass the chat
        # model entirely (e.g. clarification / handle_clarification).
        if streamed_answer and not final_answer:
            final_answer = streamed_answer

    except Exception as exc:  # noqa: BLE001
        if GraphInterrupt is not None and isinstance(exc, GraphInterrupt):
            question = str(exc) or "Could you clarify your question?"
            yield ChatStreamEvent.clarification(question).to_sse()
            try:
                langfuse_tracing.end_trace(trace_id, output="[clarification]")
            except Exception:  # noqa: BLE001
                logger.debug("end_trace failed after clarification", exc_info=True)
            return

        logger.exception("Chat pipeline error: %s", exc)
        yield ChatStreamEvent.error(
            message="An error occurred.", code="pipeline_error"
        ).to_sse()
        try:
            langfuse_tracing.end_trace(
                trace_id, output="", error=str(exc)[:200]
            )
        except Exception:  # noqa: BLE001
            logger.debug("end_trace failed after pipeline error", exc_info=True)
        return

    # Empty-answer guard. ``chat_messages.content`` is NOT NULL — inserting
    # an empty string would either crash (session path) or be wasted work
    # (sandbox path). Either way the right move is the same: emit a
    # terminal error frame so the frontend exits its loading state.
    if not final_answer:
        logger.warning(
            "Chat pipeline ended with empty final_answer for session=%s — "
            "emitting error frame",
            session_id,
        )
        yield ChatStreamEvent.error(
            message="The assistant produced no response. Please try again.",
            code="empty_response",
        ).to_sse()
        try:
            langfuse_tracing.end_trace(trace_id, output="[empty]")
        except Exception:  # noqa: BLE001
            logger.debug("end_trace failed after empty response", exc_info=True)
        return

    # The synthesizer (:mod:`src.agent.nodes.generate`) is now a LangChain
    # ``BaseChatModel`` runnable, so LangGraph's ``astream_events(version="v2")``
    # fires real ``on_chat_model_stream`` events and we yield ``delta`` frames
    # in the loop above as tokens arrive.  The synthetic tail-delta band-aid
    # that used to live here is gone.
    #
    # Two narrow fallbacks remain so the wire grammar stays stable:
    #
    # 1. **Pure-Python answer paths** — clarification / handle_clarification
    #    set ``final_answer`` in Python without calling a chat model, so
    #    ``streamed_answer`` is empty.  Emit the whole answer as a single
    #    delta so the frontend's ``currentResponse`` accumulator gets it.
    # 2. **Post-synthesis rewrite** — ``format_response`` (today a no-op)
    #    or a future ``guardrail_output`` could append text to the
    #    synthesizer's stream.  When the canonical ``final_answer`` is a
    #    proper prefix-extension of ``streamed_answer`` we emit just the
    #    suffix as a corrective delta.  Divergent rewrites (e.g. a guardrail
    #    fully replacing the answer) are NOT retracted mid-stream — the
    #    persisted ``final_answer`` will surface on next reload.
    if final_answer and final_answer != streamed_answer and final_answer.startswith(
        streamed_answer
    ):
        tail = final_answer[len(streamed_answer):]
        yield ChatStreamEvent.delta(tail).to_sse()

    # Success path. The session-chat caller passes a ``persist_assistant``
    # callback that writes ``chat_messages`` and returns the new message id.
    # The sandbox caller skips this — its contract explicitly does NOT
    # persist anything.
    message_id = ""
    if persist_assistant:
        if on_done is None:
            raise RuntimeError(
                "persist_assistant=True requires an on_done callback"
            )
        try:
            message_id = await on_done(final_answer)
        except Exception:  # noqa: BLE001
            logger.exception(
                "on_done callback failed for session=%s — emitting error frame",
                session_id,
            )
            yield ChatStreamEvent.error(
                message="Failed to save the assistant response.",
                code="persist_error",
            ).to_sse()
            try:
                langfuse_tracing.end_trace(
                    trace_id, output=final_answer, error="persist_failed"
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "end_trace failed after persist error", exc_info=True
                )
            return

    yield ChatStreamEvent.done(
        session_id=session_id,
        message_id=message_id,
        trace_id=trace_id,
        sources=sources,
    ).to_sse()
    try:
        langfuse_tracing.end_trace(trace_id, output=final_answer)
    except Exception:  # noqa: BLE001
        logger.debug("end_trace failed after success", exc_info=True)
