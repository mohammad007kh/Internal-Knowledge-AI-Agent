"""Source inspection service — test connection + AI-generate description (T-002).

This service is stateless: it does not persist anything.  Two public entry
points:

* :meth:`inspect_source` — used by ``POST /sources/inspect`` to preview a
  source connection **before** it is saved.  Tests the connection, inspects
  the schema (when the connector supports it), and asks the LLM for a short
  natural-language description.
* :meth:`generate_description` — regenerates the description for an
  already-persisted :class:`~src.models.source.Source`.  Used by
  ``POST /sources/{id}/refresh-description``.

Secrets in the ``connection`` dict are **never** echoed back: only derived
schema metadata (counts) is returned to the caller.
"""

from __future__ import annotations

import logging
import re
from typing import Any

try:  # Langfuse 4.x exposes observe at the package root.
    from langfuse import observe  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 - observability is strictly optional
    def observe(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        """No-op fallback when langfuse is unavailable or incompatible."""

        def _decorator(fn):  # type: ignore[no-untyped-def]
            return fn

        return _decorator

from src.connectors.registry import get_connector
from src.models.enums import SourceType

logger = logging.getLogger(__name__)

# Source types that represent uploaded files.  For these we do NOT attempt a
# live connection — the uploaded object lives in MinIO and is inspected after
# ingestion.  Includes both the canonical enum value and common MIME-like
# shorthand strings so the inspection endpoint is forgiving about the label.
FILE_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "file_upload",
        "pdf",
        "docx",
        "xlsx",
        "csv",
        "txt",
        "markdown",
    }
)

# Default probe query used for the *inspect* preview of a SQL source.  The
# user may not have entered their real SELECT statement yet — a connection
# preview only needs to prove the credentials/host work, so we substitute a
# trivial no-op.  ``DatabaseConnectionConfig`` requires ``query`` for SQL
# dialects, so we must supply *something*.
_INSPECT_PROBE_QUERY = "SELECT 1"

# Matches the ``user:password@`` segment of any URI so it can be masked before
# the message reaches the caller.
_CREDENTIALS_IN_URI = re.compile(r"://[^@\s]+@")


def _sanitize_error_message(msg: str) -> str:
    """Strip ``user:password@`` from any URI embedded in *msg*.

    Used on every error surfaced from the translation/connection path so a
    connection string (which the SQLAlchemy/asyncpg drivers love to embed in
    exception text) never leaks credentials back to the API caller.
    """
    return _CREDENTIALS_IN_URI.sub("://***@", msg)


DESCRIPTION_PROMPT = (
    "You are a technical writer. Given a data source schema, produce a concise "
    "(2-3 sentence) natural-language description of what this data likely "
    "contains and what questions it could answer. Be factual, avoid "
    "speculation.\n\n"
    "Source type: {source_type}\n"
    "Schema summary: {schema_summary}\n\n"
    "Description:"
)


class SourceInspectionService:
    """Inspect a (potential) source and summarise it with an LLM."""

    def __init__(self, openai_client: Any) -> None:
        self._client = openai_client

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    @observe(name="schema_inspector")
    async def inspect_source(
        self,
        source_type: str,
        connection: dict[str, Any],
    ) -> dict[str, Any]:
        """Test connection, inspect schema, generate AI description.

        Does NOT persist anything.  File-based source types short-circuit
        (the connection is implicit — the file lives in MinIO after upload).
        """
        if source_type in FILE_SOURCE_TYPES:
            return {"description": "", "schema_summary": {}}

        try:
            source_type_enum = SourceType(source_type)
        except ValueError as exc:
            raise ValueError(f"Unknown source type: {source_type}") from exc

        connector_config = connection
        if source_type_enum is SourceType.DATABASE:
            connector_config = self._to_database_connector_config(connection)

        try:
            connector = get_connector(source_type_enum, connector_config)
            ok = await connector.test_connection()
        except (ValueError, ConnectionError):
            raise
        except Exception as exc:  # noqa: BLE001 — any driver-level failure
            # Driver exceptions routinely embed the connection string; never
            # let that (or the raw exception text) reach the caller verbatim.
            raise ConnectionError(
                _sanitize_error_message(f"Could not connect to {source_type} source")
            ) from exc
        if not ok:
            raise ConnectionError(f"Could not connect to {source_type} source")

        schema_summary = await self._safe_inspect_schema(connector)
        description = await self._safe_generate_description(
            source_type=source_type,
            schema_summary=schema_summary,
        )
        return {"description": description, "schema_summary": schema_summary}

    @observe(name="refresh_description")
    async def generate_description(self, source: Any) -> str:
        """Regenerate description for an existing persisted Source.

        Because we do not have access to the decrypted connection config from
        this layer, we regenerate the description from the stored
        ``source_type`` and whatever metadata is already attached to the
        entity.
        """
        source_type_str = self._coerce_source_type(source)
        if source_type_str in FILE_SOURCE_TYPES:
            # Files do not carry a schema — nothing useful for the LLM.
            return ""
        schema_summary: dict[str, Any] = {}
        description = await self._safe_generate_description(
            source_type=source_type_str,
            schema_summary=schema_summary,
        )
        return description

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _to_database_connector_config(connection: dict[str, Any]) -> dict[str, Any]:
        """Translate the wizard's *structured* DB payload into connector shape.

        The "Add database" wizard POSTs ``connection`` in the same typed shape
        :class:`~src.schemas.source.DatabaseConnectionConfig` accepts
        (``{db_type, host, port, database, username, password, ssl_mode, ...}``),
        but :func:`~src.connectors.registry.get_connector` for a ``database``
        source builds a connector whose SQL delegate dereferences
        ``config["connection_string"]`` — so the raw structured dict raises
        ``KeyError``.  This runs the structured dict through
        :meth:`SourceService._build_database_config` (same translation used by
        the create path) to produce ``{db_type, connection_string, query?,
        ssl_mode?}`` (SQL) or ``{db_type, uri, database, collection}`` (mongo).

        Pass-throughs / safety:
          * If *connection* already carries a ``connection_string`` (legacy
            callers / direct connector shape) it is returned unchanged.
          * For SQL dialects the ``query`` field is required by
            :class:`DatabaseConnectionConfig`, but an inspect probe is just a
            connection preview — if the caller hasn't supplied one we default
            it to ``SELECT 1`` so the probe still works.
          * Any translation/validation failure is re-raised as ``ValueError``
            with a credentials-sanitised message (the ``/inspect`` route maps
            ``ValueError`` → 400, ``ConnectionError`` → 422).
        """
        # Already connector-shaped (legacy / direct callers) — leave alone.
        if "connection_string" in connection or "uri" in connection:
            return connection

        # Local imports keep the module's import graph light and avoid any
        # risk of a circular import at module load time.
        from pydantic import ValidationError  # noqa: PLC0415

        from src.schemas.source import DatabaseConnectionConfig  # noqa: PLC0415
        from src.services.source_service import SourceService  # noqa: PLC0415

        candidate = dict(connection)
        # Inspect is a connection preview, not a real ingest — the user may
        # not have typed their SELECT yet.  Default it so SQL validation passes.
        if not candidate.get("query"):
            candidate["query"] = _INSPECT_PROBE_QUERY

        try:
            typed = DatabaseConnectionConfig(**candidate)
        except ValidationError as exc:
            # Surface the field paths only — never echo the connection dict.
            paths = ", ".join(
                ".".join(str(loc) for loc in err.get("loc", ()))
                for err in exc.errors()
            )
            raise ValueError(
                _sanitize_error_message(
                    f"Invalid database connection (fields: {paths or 'unknown'})."
                )
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(
                _sanitize_error_message(f"Invalid database connection: {exc}")
            ) from exc

        try:
            return SourceService._build_database_config(typed)
        except ValueError as exc:
            raise ValueError(_sanitize_error_message(str(exc))) from exc

    @staticmethod
    def _coerce_source_type(source: Any) -> str:
        raw = getattr(source, "source_type", None) or getattr(source, "type", None)
        if raw is None:
            return ""
        return raw.value if hasattr(raw, "value") else str(raw)

    @staticmethod
    async def _safe_inspect_schema(connector: Any) -> dict[str, Any]:
        """Call ``connector.inspect_schema`` when available; never raise."""
        inspect = getattr(connector, "inspect_schema", None)
        if inspect is None:
            return {}
        try:
            schema_info = await inspect()
        except Exception as exc:  # noqa: BLE001 - best-effort inspection
            logger.warning("Schema inspection failed: %s", exc)
            return {}
        tables = schema_info.get("tables", []) if isinstance(schema_info, dict) else []
        return {
            "table_count": len(tables),
            "estimated_row_count": (
                schema_info.get("estimated_row_count", 0)
                if isinstance(schema_info, dict)
                else 0
            ),
        }

    @observe(name="schema_inspector_llm_call")
    async def _safe_generate_description(
        self,
        *,
        source_type: str,
        schema_summary: dict[str, Any],
    ) -> str:
        """Call the LLM; swallow any failure (returning empty string)."""
        prompt = DESCRIPTION_PROMPT.format(
            source_type=source_type,
            schema_summary=schema_summary,
        )
        try:
            resp = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
        except Exception as exc:  # noqa: BLE001 - observability-style fallback
            logger.warning("LLM description generation failed: %s", exc)
            return ""

        try:
            content = resp.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            logger.warning("LLM response missing expected fields: %s", exc)
            return ""
        return (content or "").strip()
