"""Unit tests for LangfuseTracingService."""

from unittest.mock import MagicMock

import pytest

from src.services.langfuse_tracing_service import LangfuseTracingService


@pytest.fixture()
def service() -> tuple[LangfuseTracingService, MagicMock]:
    # The project pins Langfuse to <3 (v2): the real client exposes ``.trace``
    # and ``get_trace_url`` but NOT ``start_observation`` (a v4 API). A bare
    # MagicMock auto-creates ``start_observation``, which would make the
    # service take the wrong (v4) branch and diverge from production. Use
    # ``spec_set`` to mirror the real v2 surface so tests exercise the live
    # code path.
    mock_lf = MagicMock(spec_set=["trace", "flush", "get_trace_url", "base_url"])
    mock_lf.base_url = "https://langfuse.example.com"
    mock_lf.get_trace_url.return_value = "https://langfuse.example.com/trace/abc-123"
    return LangfuseTracingService(langfuse=mock_lf), mock_lf


def test_start_trace_returns_uuid(service: tuple[LangfuseTracingService, MagicMock]) -> None:
    svc, mock_lf = service
    tid = svc.start_trace(session_id="s1", user_id="u1", query="test query")
    assert len(tid) == 36
    mock_lf.trace.assert_called_once()


def test_end_trace_flushes(service: tuple[LangfuseTracingService, MagicMock]) -> None:
    svc, mock_lf = service
    svc.end_trace("trace-123", output="answer text")
    mock_lf.flush.assert_called_once()


def test_trace_url_contains_id(service: tuple[LangfuseTracingService, MagicMock]) -> None:
    svc, _ = service
    url = svc.trace_url("abc-123")
    assert url is not None
    assert "abc-123" in url


def test_schema_sse_format() -> None:
    from src.schemas.chat import ChatStreamEvent, StreamEventType

    event = ChatStreamEvent(event=StreamEventType.DELTA, data={"token": "Hello"})
    sse = event.to_sse()
    # Proper SSE-spec frame: `event: <name>\ndata: <inner_json>\n\n` so the
    # frontend's parseSseFrame() picks the event name from the header line and
    # routes to the right switch case. Previously the wrapper put both fields
    # inside one data line which broke client-side dispatch entirely.
    assert sse.startswith("event: delta\n")
    assert "data: " in sse
    assert sse.endswith("\n\n")
    # Inner data line carries only the payload, not the event-name envelope.
    assert '"token": "Hello"' in sse
    assert '"event"' not in sse  # event name lives in the header, not the body
