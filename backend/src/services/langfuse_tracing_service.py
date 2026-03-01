"""Per-run Langfuse trace lifecycle management."""
from __future__ import annotations

import logging
from uuid import uuid4

from langfuse import Langfuse

logger = logging.getLogger(__name__)


class LangfuseTracingService:
    """Wraps Langfuse to create and finalise traces for LangGraph runs."""

    def __init__(self, langfuse: Langfuse) -> None:
        self._lf = langfuse

    def start_trace(self, *, session_id: str, user_id: str, query: str) -> str:
        """Create a new Langfuse trace and return its trace_id."""
        trace_id = str(uuid4())
        self._lf.trace(  # type: ignore[attr-defined]
            id=trace_id,
            name="chat_pipeline",
            user_id=user_id,
            session_id=session_id,
            input={"query": query[:500]},
            metadata={"session_id": session_id},
        )
        logger.debug(
            "langfuse trace started trace_id=%s session=%s", trace_id, session_id
        )
        return trace_id

    def end_trace(
        self, trace_id: str, *, output: str, error: str | None = None
    ) -> None:
        """Update the trace with the final output and flush."""
        self._lf.trace(id=trace_id, output={"answer": output[:1000], "error": error})  # type: ignore[attr-defined]
        self._lf.flush()
        logger.debug("langfuse trace ended trace_id=%s", trace_id)

    def trace_url(self, trace_id: str) -> str | None:
        """Return Langfuse UI URL for this trace (debugging only)."""
        try:
            return f"{self._lf.base_url}/trace/{trace_id}"  # type: ignore[attr-defined]
        except AttributeError:
            return None
