"""Per-run Langfuse trace lifecycle management.

Langfuse is optional observability. When ``LANGFUSE_SECRET_KEY`` /
``LANGFUSE_PUBLIC_KEY`` are not configured, a :class:`NullLangfuse` stub is
used that silently no-ops every call the pipeline makes. All public helpers
on this module tolerate either a real ``langfuse.Langfuse`` client or the
null stub, so the chat pipeline keeps working in both cases.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class _NullSpan:
    """No-op span compatible with the methods the pipeline calls on spans."""

    def update(self, **_kwargs: Any) -> "_NullSpan":
        return self

    def end(self, **_kwargs: Any) -> None:
        return None

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class NullLangfuse:
    """Silent stand-in for :class:`langfuse.Langfuse`.

    Implements the subset of the Langfuse API that the pipeline invokes
    (``.trace``, ``.span``, ``.start_span``, ``.start_observation``,
    ``.flush``, ``.base_url``) as no-ops so calls never crash when Langfuse
    credentials are absent.
    """

    base_url: str = ""

    def trace(self, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def span(self, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def start_span(self, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def start_observation(self, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def _is_enabled(client: Any) -> bool:
    """Return True when *client* looks like a real Langfuse client."""
    return client is not None and not isinstance(client, NullLangfuse)


class LangfuseTracingService:
    """Wraps a Langfuse client (real or null) to manage chat traces."""

    def __init__(self, langfuse: Any) -> None:
        self._lf = langfuse

    def start_trace(self, *, session_id: str, user_id: str, query: str) -> str:
        """Create a trace id (and, if enabled, a Langfuse observation).

        Returns the trace id regardless so upstream code has a stable
        identifier even when Langfuse is disabled.
        """
        trace_id = str(uuid4())
        if not _is_enabled(self._lf):
            return trace_id

        try:
            # Langfuse v4 uses start_observation (with as_type='span') and
            # update_current_trace for trace-level metadata. Older v2/v3
            # clients exposed .trace(); fall back to that if present.
            if hasattr(self._lf, "start_observation"):
                span = self._lf.start_observation(
                    name="chat_pipeline",
                    as_type="span",
                    input={"query": query[:500]},
                    metadata={"session_id": session_id, "user_id": user_id},
                )
                # Best-effort trace metadata on v4 clients
                update_trace = getattr(self._lf, "update_current_trace", None)
                if callable(update_trace):
                    update_trace(  # pragma: no cover - network side effect
                        session_id=session_id,
                        user_id=user_id,
                        input={"query": query[:500]},
                    )
                end_span = getattr(span, "end", None)
                if callable(end_span):
                    end_span()
            elif hasattr(self._lf, "trace"):
                self._lf.trace(  # type: ignore[attr-defined]
                    id=trace_id,
                    name="chat_pipeline",
                    user_id=user_id,
                    session_id=session_id,
                    input={"query": query[:500]},
                    metadata={"session_id": session_id},
                )
        except Exception:  # noqa: BLE001 - observability must not break chat
            logger.debug("langfuse start_trace failed; continuing", exc_info=True)

        logger.debug(
            "langfuse trace started trace_id=%s session=%s", trace_id, session_id
        )
        return trace_id

    def end_trace(
        self, trace_id: str, *, output: str, error: str | None = None
    ) -> None:
        """Record final output and flush the Langfuse client."""
        if not _is_enabled(self._lf):
            return

        try:
            update_trace = getattr(self._lf, "update_current_trace", None)
            if callable(update_trace):
                update_trace(  # pragma: no cover - network side effect
                    output={"answer": output[:1000], "error": error},
                )
            elif hasattr(self._lf, "trace"):
                self._lf.trace(  # type: ignore[attr-defined]
                    id=trace_id,
                    output={"answer": output[:1000], "error": error},
                )
            flush = getattr(self._lf, "flush", None)
            if callable(flush):
                flush()
        except Exception:  # noqa: BLE001 - observability must not break chat
            logger.debug("langfuse end_trace failed; continuing", exc_info=True)

        logger.debug("langfuse trace ended trace_id=%s", trace_id)

    def trace_url(self, trace_id: str) -> str | None:
        """Return a URL to view *trace_id* in the Langfuse UI, if available."""
        if not _is_enabled(self._lf):
            return None
        try:
            get_url = getattr(self._lf, "get_trace_url", None)
            if callable(get_url):
                return get_url()  # type: ignore[no-any-return]
            base_url = getattr(self._lf, "base_url", None)
            if base_url:
                return f"{base_url}/trace/{trace_id}"
        except Exception:  # noqa: BLE001
            return None
        return None
