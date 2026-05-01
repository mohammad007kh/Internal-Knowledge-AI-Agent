"""source_router — LangGraph node that selects which of the user's
accessible sources to query and which (if any) should be routed to
``text_to_query`` instead of vector retrieval.

Resolver slot: ``source_router``.

Inputs (from state):
* ``query`` — user question.
* ``source_ids`` — UUIDs (as strings) of sources the user has access to.

The router pulls each source's ``name``, ``source_type`` and
``description`` from the database via the supplied
:class:`SourceRepository` so the LLM has enough context to choose.

State writes:
* ``selected_source_ids`` — subset of ``source_ids``.
* ``text_to_query_source_ids`` — subset of selected, all type=database.

Defensive fallbacks:
* Empty ``source_ids`` → both lists empty.
* DB or LLM error → ``selected_source_ids = source_ids`` (route to all),
  ``text_to_query_source_ids = []``.  The pipeline never hard-fails.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState
from src.models.enums import SourceType
from src.prompts import load_prompt

if TYPE_CHECKING:
    from langfuse import Langfuse
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.source_repository import SourceRepository
    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "source_router"

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "source_routing_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["selected_source_ids", "use_text_to_query_for"],
            "properties": {
                "selected_source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "use_text_to_query_for": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


def _safe_uuids(values: list[Any]) -> list[str]:
    """Coerce arbitrary list entries to validated UUID strings."""
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        try:
            uuid.UUID(v)
        except (ValueError, TypeError):
            continue
        out.append(v)
    return out


async def _load_catalog(
    *,
    db_session: AsyncSession,
    source_repository: SourceRepository,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch ``(id, name, type, description)`` rows for *source_ids*."""
    try:
        uuids: list[uuid.UUID] = []
        for sid in source_ids:
            try:
                uuids.append(uuid.UUID(sid))
            except (ValueError, TypeError):
                continue
        if not uuids:
            return []
        # Repository methods accept session per-call (Slice C contract).
        # Some repos still hold their session in ``__init__``; use the
        # session-aware path when available.
        rows = await source_repository.list_by_ids(uuids)
        catalog: list[dict[str, Any]] = []
        for row in rows:
            catalog.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "type": str(row.source_type),
                    "description": row.description or "",
                }
            )
        return catalog
    except Exception:  # noqa: BLE001
        logger.warning(
            "source_router: failed to load source catalog — falling back to id-only",
            exc_info=True,
        )
        return [{"id": sid, "name": sid, "type": "unknown", "description": ""} for sid in source_ids]


async def _call_llm(
    query: str,
    catalog: list[dict[str, Any]],
    *,
    ai_model_resolver: AIModelResolver,
) -> tuple[list[str], list[str]]:
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    user_payload = json.dumps({"sources": catalog, "question": query})
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_payload},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    selected = _safe_uuids(payload.get("selected_source_ids") or [])
    text_to_query = _safe_uuids(payload.get("use_text_to_query_for") or [])
    return selected, text_to_query


async def route_sources(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    db_session: AsyncSession,
    source_repository: SourceRepository,
    langfuse: Langfuse,
) -> dict[str, Any]:
    """Pick the subset of accessible sources to retrieve from.

    Always returns a non-empty ``selected_source_ids`` when the input had
    accessible sources — defensive fallback to the full input list on any
    error or empty selection.
    """
    accessible_ids: list[str] = list(state.get("source_ids") or [])
    query: str = (state.get("query") or "").strip()

    if not accessible_ids or not query:
        return {"selected_source_ids": [], "text_to_query_source_ids": []}

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={"query": query, "source_count": len(accessible_ids)},
    )
    try:
        catalog = await _load_catalog(
            db_session=db_session,
            source_repository=source_repository,
            source_ids=accessible_ids,
        )
        # Build {id: source_type} for filtering text_to_query targets.
        type_by_id = {row["id"]: row["type"] for row in catalog}

        try:
            selected, text_to_query_ids = await _call_llm(
                query, catalog, ai_model_resolver=ai_model_resolver
            )
        except Exception:  # noqa: BLE001 - degrade
            logger.warning(
                "source_router: LLM call failed — routing to all accessible sources",
                exc_info=True,
            )
            selected = list(accessible_ids)
            text_to_query_ids = []

        # Keep only ids that the user actually has access to.
        accessible_set = set(accessible_ids)
        selected = [sid for sid in selected if sid in accessible_set]
        if not selected:
            logger.info(
                "source_router: empty selection — falling back to all accessible (%d)",
                len(accessible_ids),
            )
            selected = list(accessible_ids)

        # text_to_query subset must be (a) in selected, (b) database type.
        selected_set = set(selected)
        text_to_query_ids = [
            sid
            for sid in text_to_query_ids
            if sid in selected_set
            and type_by_id.get(sid) == SourceType.DATABASE.value
        ]

        span.update(
            output={
                "selected_count": len(selected),
                "text_to_query_count": len(text_to_query_ids),
            }
        )
        logger.info(
            "source_router: selected=%d text_to_query=%d (of %d accessible)",
            len(selected),
            len(text_to_query_ids),
            len(accessible_ids),
        )
        return {
            "selected_source_ids": selected,
            "text_to_query_source_ids": text_to_query_ids,
        }
    finally:
        span.end()
