"""retrieve_context — LangGraph node that embeds the user query and fetches
the top-K most relevant chunks, scoped to the caller's allowed source IDs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langfuse import Langfuse

from src.agent.state import AgentState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chunk_repository import ChunkRepository
    from src.services.embedding_service_factory import EmbeddingServiceFactory

logger = logging.getLogger(__name__)

_RESULT_LIMIT = 10
# Cosine-distance ceiling for retrieved chunks. Bumped from 0.75 to 0.85
# (FX5/RC2): empirically the previous gate was too tight for cross-lingual
# hits (English question against a French source), and the score
# distribution log added below now makes future tuning trivial without
# pivoting Langfuse traces. Lower distance still = more similar.
# TODO: make this per-embedder via a column on `embedders` so swapping to
# 3-large or BGE doesn't require a code change.
SIMILARITY_THRESHOLD = 0.85

# When the analyzer degrades, prepend the last N user turns to the embedding
# query as a defense-in-depth measure so pronoun-resolution failures don't
# silently kill recall. See FX5/RC4 stop-gap.
_DEGRADED_PRIOR_TURNS = 2


def _last_user_turn_texts(
    messages: list[Any] | None, n: int, *, exclude: str = ""
) -> list[str]:
    """Return the last *n* user-turn texts in chronological order.

    The current-turn ``HumanMessage`` is appended to ``state["messages"]``
    by ``chat.py`` before the graph runs, so it would otherwise show up
    here and produce a duplicate when joined with the rewritten query.
    Pass ``exclude`` (the current rewritten/base query) to skip any
    matching turn.

    Defensive: messages can be langchain ``BaseMessage`` subclasses or
    plain dicts.  Read role from ``.type`` / ``.role`` and content from
    ``.content`` / ``["content"]``.
    """
    if not messages:
        return []
    exclude_norm = exclude.strip()
    out: list[str] = []
    for msg in reversed(messages):
        role = (
            getattr(msg, "type", None)
            or getattr(msg, "role", None)
            or (msg.get("role") if isinstance(msg, dict) else None)
        )
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if role in ("human", "user"):
            text = content.strip()
            if text == exclude_norm:
                continue
            out.append(text)
            if len(out) >= n:
                break
    out.reverse()
    return out


def _build_query_list(state: AgentState, base_query: str) -> list[str]:
    """Build the ordered, deduped list of queries to embed.

    Always starts with ``base_query`` (the rewritten/resolved query from
    ``query_analyzer``), followed by any other variants the analyzer
    produced.  When the analyzer degraded, the base_query is augmented
    with prior user turns joined by " | " — see FX5/RC4 stop-gap.
    """
    variants_in: list[str] = list(state.get("query_variants") or [])
    queries: list[str] = []
    seen: set[str] = set()

    if state.get("query_analyzer_degraded") is True:
        prior = _last_user_turn_texts(
            state.get("messages"), _DEGRADED_PRIOR_TURNS, exclude=base_query
        )
        if prior:
            augmented = " | ".join([*prior, base_query])
            queries.append(augmented)
            seen.add(augmented)

    if base_query and base_query not in seen:
        queries.append(base_query)
        seen.add(base_query)

    for v in variants_in:
        if isinstance(v, str) and v.strip() and v not in seen:
            queries.append(v)
            seen.add(v)
    return queries


async def retrieve_context(
    state: AgentState,
    *,
    embedding_service_factory: EmbeddingServiceFactory,
    chunk_repository: ChunkRepository,
    db_session: AsyncSession,
    langfuse: Langfuse,
) -> dict:  # type: ignore[type-arg]
    """Embed the user query and retrieve the top-K most relevant chunks.

    Enforces FR-019: only chunks whose source_id appears in
    ``state["source_ids"]`` are ever returned.

    When the v2 ``source_router`` has narrowed the accessible sources for
    this query it writes ``state["selected_source_ids"]`` — a subset of
    ``state["source_ids"]``.  We prefer that subset so the LLM-driven
    routing actually filters retrieval; v1 (and any v2 path where the
    router degraded to empty) still fall back to the full allowlist.

    Multi-variant retrieval (FX5/RC1): when ``state["query_variants"]``
    is populated by ``query_analyzer``, every variant is embedded and
    searched in parallel.  Results are merged by ``chunk_id`` keeping the
    minimum cosine distance across variants, then sorted ascending and
    filtered by :data:`SIMILARITY_THRESHOLD`.
    """
    # Defensive: if the analyzer skipped or failed before us, normalize.
    state.setdefault("query_analyzer_degraded", False)  # type: ignore[misc]

    accessible_ids: list[str] = state.get("source_ids", []) or []
    selected_ids: list[str] = state.get("selected_source_ids") or []
    source_ids: list[str] = selected_ids if selected_ids else accessible_ids
    base_query: str = (state.get("query") or "").strip()

    # FR-019: empty allowlist → no results, no embedding call
    if not source_ids:
        logger.warning(
            "retrieve_context: empty source_ids for user=%s — returning empty",
            state.get("user_id"),
        )
        return {"retrieved_chunks": []}

    if not base_query:
        return {"retrieved_chunks": []}

    queries = _build_query_list(state, base_query)
    if not queries:
        return {"retrieved_chunks": []}

    # Langfuse v2 SDK uses .span(...) (not .start_span(...) — that's v3).
    # Project is pinned to <3 since v3 dropped the .trace() API used elsewhere
    # (commit 1e64fe1).  Match every other node's pattern: pass trace_id so
    # the span hangs off the request's trace.
    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name="retrieve_context",
        input={
            "queries": queries,
            "source_ids": source_ids,
            "degraded_analyzer": state.get("query_analyzer_degraded") is True,
        },
    )

    try:
        # ``for_active`` returns both the service and the active embedder id
        # in one call so the retrieve node can apply the defensive
        # ``embedder_id`` filter without a duplicate DB roundtrip.
        embedding_service, active_id = await embedding_service_factory.for_active()

        # Embed every variant in parallel — the embedding service supports
        # concurrent calls and the rewriter caps variants at 3 anyway.
        # return_exceptions=True so a single transient failure doesn't kill
        # the whole retrieval; we recover what we can and log the rest.
        embed_outcomes = await asyncio.gather(
            *(embedding_service.embed_query(q) for q in queries),
            return_exceptions=True,
        )
        ok_embeddings: list[tuple[str, list[float]]] = []
        embed_failures = 0
        for q, outcome in zip(queries, embed_outcomes, strict=True):
            if isinstance(outcome, BaseException):
                embed_failures += 1
                logger.warning(
                    "retrieve.embed_failed query=%r err=%s",
                    q,
                    type(outcome).__name__,
                )
                continue
            ok_embeddings.append((q, outcome))

        if not ok_embeddings:
            # All variants failed to embed — re-raise the first to keep
            # error_handler semantics (state["error"]="retrieval_failed").
            first_err = next(
                e for e in embed_outcomes if isinstance(e, BaseException)
            )
            raise first_err

        # Run similarity search per surviving variant in parallel; same
        # partial-failure tolerance.
        search_outcomes = await asyncio.gather(
            *(
                chunk_repository.similarity_search(
                    db_session,
                    query_embedding=emb,
                    source_ids=source_ids,
                    limit=_RESULT_LIMIT,
                    embedder_id=active_id,
                )
                for _, emb in ok_embeddings
            ),
            return_exceptions=True,
        )
        search_results: list[list[tuple[Any, float]]] = []
        search_failures = 0
        for (q, _), outcome in zip(ok_embeddings, search_outcomes, strict=True):
            if isinstance(outcome, BaseException):
                search_failures += 1
                logger.warning(
                    "retrieve.search_failed query=%r err=%s",
                    q,
                    type(outcome).__name__,
                )
                continue
            search_results.append(outcome)

        if not search_results:
            first_err = next(
                e for e in search_outcomes if isinstance(e, BaseException)
            )
            raise first_err

        # Merge by chunk_id keeping min(distance) across variants. Track
        # per-variant top-3 distances for tracing.
        per_variant_top3: list[list[float]] = []
        merged: dict[str, tuple[Any, float]] = {}
        for pairs in search_results:
            sorted_pairs = sorted(pairs, key=lambda p: p[1])
            per_variant_top3.append(
                [round(d, 4) for _, d in sorted_pairs[:3]]
            )
            for chunk, score in pairs:
                cid = str(chunk.id)
                existing = merged.get(cid)
                if existing is None or score < existing[1]:
                    merged[cid] = (chunk, score)

        # Sort merged set ascending by distance, take top-K.
        ordered = sorted(merged.values(), key=lambda p: p[1])[:_RESULT_LIMIT]
        all_distances = [score for _, score in ordered]

        kept_pairs = [(c, s) for c, s in ordered if s < SIMILARITY_THRESHOLD]
        dropped_pairs = [(c, s) for c, s in ordered if s >= SIMILARITY_THRESHOLD]

        # Always emit the score-distribution log — even when everything was
        # dropped — so future "why no chunks?" debugging is trivial without
        # pivoting Langfuse traces.  See FX5/RC2.
        logger.info(
            "retrieve.score_distribution top3_dist=%s kept=%d dropped=%d threshold=%.2f variants=%d",
            [round(d, 3) for d in all_distances[:3]],
            len(kept_pairs),
            len(dropped_pairs),
            SIMILARITY_THRESHOLD,
            len(queries),
        )

        chunks = [
            {
                "chunk_id": str(chunk.id),
                "source_id": str(chunk.source_id),
                "text": chunk.chunk_text,
                "score": round(score, 4),
                "document_title": (chunk.metadata_ or {}).get("document_title"),
                "page_number": (chunk.metadata_ or {}).get("page_number"),
                "source_name": (chunk.metadata_ or {}).get("source_name"),
            }
            for chunk, score in kept_pairs
        ]

        if not chunks:
            span.update(
                output={
                    "chunk_count": 0,
                    "below_threshold": True,
                    "per_variant_top3": per_variant_top3,
                    "merged_candidates": len(ordered),
                }
            )
            return {"retrieved_chunks": []}

        span.update(
            output={
                "chunk_count": len(chunks),
                "per_variant_top3": per_variant_top3,
                "merged_candidates": len(ordered),
            }
        )
        logger.info(
            "retrieve_context: found %d chunks (above threshold) for query len=%d (variants=%d)",
            len(chunks),
            len(base_query),
            len(queries),
        )
        return {"retrieved_chunks": chunks}

    except Exception:
        logger.exception("retrieve_context failed")
        span.update(output={"chunk_count": 0, "error": True})
        return {"retrieved_chunks": [], "error": "retrieval_failed"}
    finally:
        span.end()
