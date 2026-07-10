"""Unit tests for `_scoped_pipeline` — the SSE pipeline session-leak fix (#276).

The guarantee: `Container.pipeline()`/`agentic_pipeline()` build ~5 stateful DB
sessions (db_session + chunk/chat_session/chat_message/source repos); the helper
scopes every one of them to the stream so ALL are closed (connections returned
to the pool) on BOTH normal completion AND an exception mid-stream
(GeneratorExit / CancelledError / error).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

pytestmark = pytest.mark.asyncio


class _FakeSession:
    """Minimal async-context-manager session that records its own close."""

    def __init__(self, log: list) -> None:
        self.closed = False
        self._log = log

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc) -> bool:  # noqa: ANN002
        self.closed = True
        self._log.append(self)
        return False


def _session_factory(log: list):
    """Return a sessionmaker-shaped callable minting fresh fake sessions."""

    def _factory() -> _FakeSession:
        return _FakeSession(log)

    return _factory


# Session-holder kwargs the helper must supply so none falls back to a
# Container-minted, unscoped session. guardrail_service is NO LONGER here: as of
# #285 it owns a session_factory and self-scopes per DB touch, so the helper no
# longer overrides it (and no longer touches the Container).
_HOLDER_KWARGS = {
    "db_session",
    "chunk_repository",
    "chat_session_repository",
    "chat_message_repository",
    "source_repository",
}
# Total scoped sessions the helper opens: db_session + 4 repos (guardrail moved
# into the DI graph in #285).
_EXPECTED_SESSIONS = 5


async def test_scoped_pipeline_wires_all_holders_and_closes_on_normal_exit() -> None:
    from src.api.v1.chat import _scoped_pipeline

    closed: list = []
    captured: dict = {}

    def provider(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return "PIPELINE"

    async with _scoped_pipeline(provider, _session_factory(closed)) as pipe:
        assert pipe == "PIPELINE"
        # Every session-holder was supplied (incl. guardrail_service).
        assert _HOLDER_KWARGS.issubset(captured.keys())
        # Nothing closed while the stream is live.
        assert closed == []

    # On exit: every scoped session closed → connections returned to the pool.
    assert len(closed) == _EXPECTED_SESSIONS
    assert all(s.closed for s in closed)


async def test_scoped_pipeline_closes_all_sessions_on_exception() -> None:
    """A mid-stream failure (models GeneratorExit/CancelledError) must still
    close every scoped session — this is the actual leak-on-disconnect fix."""
    from src.api.v1.chat import _scoped_pipeline

    closed: list = []

    def provider(**_kwargs):  # noqa: ANN003
        return "PIPELINE"

    with pytest.raises(RuntimeError):
        async with _scoped_pipeline(provider, _session_factory(closed)):
            raise RuntimeError("stream aborted")

    assert len(closed) == _EXPECTED_SESSIONS
    assert all(s.closed for s in closed)
