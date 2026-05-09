"""Unit tests for the text_to_query LangGraph node — incl. SQL safety."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.nodes.text_to_query import text_to_query
from src.models.enums import SourceType
from src.services.ai_model_resolver import AIModelClient
from src.services.db_safety import inject_limit, validate_sql


def is_safe_sql(sql: str, dialect: str = "postgres") -> tuple[bool, str]:
    """Test-local adaptor — keeps these tests' shape stable across the
    rename from the old regex-based helper to :func:`validate_sql`."""
    result = validate_sql(sql, dialect=dialect)
    if result.is_safe:
        return True, ""
    return False, result.reason or ""


def wrap_with_limit(sql: str, *, limit: int = 100) -> str:
    return inject_limit(sql, n=limit)


# ---------------------------------------------------------------------------
# Pure SQL safety checks
# ---------------------------------------------------------------------------


def test_rejects_non_select() -> None:
    safe, reason = is_safe_sql("UPDATE users SET role='admin'")
    assert not safe
    assert reason  # non-empty reason on rejection


def test_rejects_semicolon_multi_statement() -> None:
    # An interior semicolon is rejected as multi-statement.
    safe, _ = is_safe_sql("SELECT 1; DROP TABLE users")
    assert not safe


def test_strips_single_trailing_semicolon() -> None:
    safe, reason = is_safe_sql("SELECT id FROM t;")
    assert safe
    assert reason == ""


def test_rejects_dml_in_cte() -> None:
    safe, _ = is_safe_sql("WITH x AS (DELETE FROM t RETURNING *) SELECT 1 FROM x")
    assert not safe


def test_rejects_multistatement_with_dml() -> None:
    safe, _ = is_safe_sql("SELECT 1; DELETE FROM t")
    assert not safe


def test_accepts_plain_select() -> None:
    safe, _ = is_safe_sql("SELECT id, name FROM users WHERE id = 1")
    assert safe


def test_accepts_column_named_like_keyword() -> None:
    """Old regex-blocklist impl rejected this on the substring ``update``.

    The new sqlglot-based impl walks the AST, so column names that happen
    to share spelling with DML keywords are no longer false-positives.
    """
    safe, reason = is_safe_sql(
        "SELECT id, update_at, delete_at, call FROM events WHERE update_at IS NOT NULL"
    )
    assert safe, f"false-positive resurrected: {reason!r}"


def test_wraps_with_limit_100() -> None:
    wrapped = wrap_with_limit("SELECT id FROM t")
    upper = wrapped.upper()
    assert "LIMIT" in upper
    assert "100" in wrapped
    # No more subquery-wrapping — that produced invalid MSSQL.
    assert "AS _q" not in wrapped


def test_wrap_replaces_larger_existing_limit() -> None:
    wrapped = wrap_with_limit("SELECT id FROM t LIMIT 1000")
    assert "100" in wrapped
    assert "1000" not in wrapped


# ---------------------------------------------------------------------------
# Node-level integration with mocks
# ---------------------------------------------------------------------------


def _resolver_for(http_client) -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.0,
        max_tokens=1024,
        custom_prompt=None,
        capabilities={},
        http_client=http_client,
    )
    return resolver


def _openai_returning_text(text: str) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = text
    client.chat.completions.create.return_value = completion
    return client


def _make_source(*, type_: SourceType = SourceType.DATABASE) -> MagicMock:
    src = MagicMock()
    src.id = uuid.uuid4()
    src.name = "orders_db"
    src.source_type = type_
    src.description = "Orders schema"
    src.config_encrypted = b"encrypted-blob"
    return src


def _langfuse() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


def _state(target_ids: list[str], existing_chunks: list | None = None) -> dict:
    return {
        "query": "How many orders shipped today?",
        "trace_id": "trace-1",
        "session_id": "sess-1",
        "user_id": "user-1",
        "text_to_query_source_ids": target_ids,
        "retrieved_chunks": list(existing_chunks or []),
    }


@pytest.mark.asyncio
async def test_no_targets_is_noop() -> None:
    resolver = _resolver_for(_openai_returning_text("SELECT 1"))
    result = await text_to_query(
        _state([]),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=AsyncMock(),
        langfuse=_langfuse(),
    )
    assert result == {}
    resolver.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_falls_through_on_unsafe_sql() -> None:
    """When LLM produces unsafe SQL, the source is skipped, no rows added."""
    src = _make_source()
    repo = AsyncMock()
    repo.list_by_ids.return_value = [src]
    # LLM returns DELETE — must be rejected.
    resolver = _resolver_for(_openai_returning_text("DELETE FROM orders"))

    with patch(
        "src.agent.nodes.text_to_query._decrypt_source_config",
        return_value={"connection_string": "postgresql+asyncpg://x"},
    ):
        result = await text_to_query(
            _state([str(src.id)]),
            ai_model_resolver=resolver,
            db_session=AsyncMock(),
            source_repository=repo,
            langfuse=_langfuse(),
        )

    # Unsafe SQL → no chunks added, no execution.
    assert result.get("retrieved_chunks", []) == []
    assert result.get("generated_sql", {}) == {}


@pytest.mark.asyncio
async def test_appends_rows_as_chunks_on_safe_sql() -> None:
    src = _make_source()
    repo = AsyncMock()
    repo.list_by_ids.return_value = [src]
    resolver = _resolver_for(_openai_returning_text("SELECT id, total FROM orders"))

    fake_row = {"id": 1, "total": 99.99}

    with patch(
        "src.agent.nodes.text_to_query._decrypt_source_config",
        return_value={"connection_string": "postgresql+asyncpg://x"},
    ), patch(
        "src.agent.nodes.text_to_query._execute",
        new=AsyncMock(return_value=[fake_row]),
    ):
        result = await text_to_query(
            _state([str(src.id)]),
            ai_model_resolver=resolver,
            db_session=AsyncMock(),
            source_repository=repo,
            langfuse=_langfuse(),
        )

    chunks = result["retrieved_chunks"]
    assert len(chunks) == 1
    assert chunks[0]["source_id"] == str(src.id)
    assert "id: 1" in chunks[0]["text"]
    # Slot must be the EXACT seeded name.
    resolver.resolve.assert_awaited_once_with("text_to_query")
    # generated_sql is wrapped with LIMIT 100.
    sql = result["generated_sql"][str(src.id)]
    assert "LIMIT 100" in sql


@pytest.mark.asyncio
async def test_skips_non_database_type() -> None:
    src = _make_source(type_=SourceType.WEB_URL)
    repo = AsyncMock()
    repo.list_by_ids.return_value = [src]
    resolver = _resolver_for(_openai_returning_text("SELECT 1"))

    with patch(
        "src.agent.nodes.text_to_query._decrypt_source_config",
        return_value={"connection_string": "postgresql+asyncpg://x"},
    ):
        result = await text_to_query(
            _state([str(src.id)]),
            ai_model_resolver=resolver,
            db_session=AsyncMock(),
            source_repository=repo,
            langfuse=_langfuse(),
        )

    assert result.get("retrieved_chunks", []) == []
    # No LLM call made for non-DB sources.
    resolver.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_skips_on_missing_connection_string() -> None:
    src = _make_source()
    repo = AsyncMock()
    repo.list_by_ids.return_value = [src]
    resolver = _resolver_for(_openai_returning_text("SELECT 1"))

    with patch(
        "src.agent.nodes.text_to_query._decrypt_source_config",
        return_value=None,
    ):
        result = await text_to_query(
            _state([str(src.id)]),
            ai_model_resolver=resolver,
            db_session=AsyncMock(),
            source_repository=repo,
            langfuse=_langfuse(),
        )

    assert result.get("retrieved_chunks", []) == []
