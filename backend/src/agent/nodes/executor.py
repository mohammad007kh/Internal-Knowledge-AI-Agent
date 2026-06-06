"""execute_step — LangGraph executor node (T-053).

Runs ONE plan step in isolation:
  1. Permission re-clip (FR-009): step's source_id must be in permitted set.
  2. R1b interpolation: resolves {{sN.output}} refs from past_steps before dispatch.
  3. Loads step-scoped schema context via load_schema_context_chunks.
  4. Calls vector retrieval primitives as functions (embedding + similarity search).
  5. Emits step SSE events (started + finished/failed) into step_event_data state field.
  6. Appends StepResult to past_steps; does NOT touch turn-wide retrieved_chunks.

Security Rule 5: narration is application-generated (first-3 titles + count) — never
a raw slice of result rows.
Security Rule 1: LLM-generated fields (label, sub_query, step_id) are sanitized
before logging and html.escape'd before inclusion in event envelopes.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from src.agent.state import AgentState, PlanStep, StepResult, _BoundInputs, _Verification

if TYPE_CHECKING:
    from langfuse import Langfuse
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.chunk_repository import ChunkRepository
    from src.services.embedding_service_factory import EmbeddingServiceFactory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-import shim for load_schema_context_chunks
#
# Importing _schema_context at module scope would pull in src.services.__init__
# → connectors → StorageService → config.Settings(), which validates required
# env-vars and breaks unit tests that run without a .env file.  The shim below
# keeps the module-level *name* (so unittest.mock.patch can replace it) while
# deferring the real import until the first call.
# ---------------------------------------------------------------------------


async def load_schema_context_chunks(
    db: AsyncSession,
    *,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    """Lazy shim — delegates to src.agent.nodes._schema_context on first call."""
    from src.agent.nodes._schema_context import (  # noqa: PLC0415
        load_schema_context_chunks as _real,
    )
    return await _real(db, source_ids=source_ids)


_MAX_REF_ITEMS = 50              # R1b: list outputs capped before comma-join
_MAX_ITEM_CHARS = 500            # per chunk text item — prevents injection via huge ref values
_SIMILARITY_LIMIT = 10           # max vector-search results per step
_NARRATION_MAX = 200             # hard char cap on step summary
_MAX_RESOLVED_QUERY_CHARS = 8_000  # embedding API token limit buffer
_REF_PATTERN = re.compile(r"\{\{(s\d+)\.output\}\}")
_LOG_UNSAFE = re.compile(
    r"[\r\n\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]"
)


def _safe_log(value: str, max_len: int = 200) -> str:
    """Strip control + BiDi override characters from LLM-generated strings before logging."""
    cleaned = _LOG_UNSAFE.sub("?", str(value))
    return unicodedata.normalize("NFC", cleaned)[:max_len]


# ---------------------------------------------------------------------------
# R1b interpolation
# ---------------------------------------------------------------------------


def _resolve_ref(ref_step_id: str, past_steps: list[dict]) -> tuple[str, bool]:
    """Resolve one {{sN.output}} reference.

    Returns (joined_text, truncated). Caps each item at _MAX_ITEM_CHARS to
    prevent injection payloads from inflating resolved_query. Uses a safe
    placeholder when no matching past step exists.
    """
    for step in reversed(past_steps):
        if step["step_id"] == ref_step_id:
            chunks = step.get("output_chunks") or []
            items = [
                c.get("text", "")[:_MAX_ITEM_CHARS]
                for c in chunks
                if c.get("text")
            ]
            truncated = len(items) > _MAX_REF_ITEMS
            return ", ".join(items[:_MAX_REF_ITEMS]), truncated
    return f"(no output from {ref_step_id})", False


def _interpolate(
    sub_query: str,
    past_steps: list[dict],
) -> tuple[str, _BoundInputs | None]:
    """Resolve all {{sN.output}} references in sub_query per R1b.

    Returns (resolved_query, bound_inputs). bound_inputs is None when there
    are no refs in the sub_query.
    """
    step_ids = _REF_PATTERN.findall(sub_query)
    if not step_ids:
        return sub_query, None

    resolved = sub_query
    refs: dict[str, str] = {}
    any_truncated = False

    for ref_id in dict.fromkeys(step_ids):  # deduplicate, preserve order
        text, trunc = _resolve_ref(ref_id, past_steps)
        resolved = resolved.replace(f"{{{{{ref_id}.output}}}}", text)
        refs[ref_id] = text
        if trunc:
            any_truncated = True

    return resolved, _BoundInputs(refs=refs, truncated=any_truncated)


# ---------------------------------------------------------------------------
# Narration (Security Rule 5 — application-generated, never raw rows)
# ---------------------------------------------------------------------------


def _narrate(chunks: list[dict[str, Any]]) -> str:
    """Build ≤200-char narration from output chunks.

    Format: "Got N result(s): Title A, Title B, Title C (+M more)"
    Uses html-escaped document_title → source_name as labels (Security Rule 1).
    Never includes raw chunk text (Security Rule 5).
    """
    if not chunks:
        return "Step completed with no results."

    count = len(chunks)
    labels: list[str] = []
    for c in chunks[:3]:
        raw_label = c.get("document_title") or c.get("source_name") or ""
        if raw_label:
            labels.append(html.escape(str(raw_label).strip(), quote=True))

    if not labels:
        return f"Got {count} result(s)."

    # extra = chunks beyond the first-3 window (not "chunks without a title")
    extra = max(0, count - 3)
    joined = ", ".join(labels)
    suffix = f" (+{extra} more)" if extra > 0 else ""
    narration = f"Got {count} result(s): {joined}{suffix}"
    return narration[:_NARRATION_MAX]


# ---------------------------------------------------------------------------
# Step event builder
# ---------------------------------------------------------------------------


def _step_event(
    *,
    step_id: str,
    label: str,
    state_name: str,
    summary: str | None,
    current: int,
    total: int,
) -> dict[str, Any]:
    """Build a step SSE event payload matching contracts/sse-events.md.

    label is html.escape'd (Security Rule 1) — it originates from the LLM-generated
    PlanStep.description and may be rendered in downstream LLM contexts.
    """
    return {
        "step_id": step_id,
        "role": "executor",
        "state": state_name,
        "label": html.escape(label[:_NARRATION_MAX], quote=True),
        "summary": summary,
        "progress": {"current": current, "total": total},
    }


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------


async def execute_step(
    state: AgentState,
    *,
    langfuse: Langfuse,
    embedding_service_factory: EmbeddingServiceFactory,
    chunk_repository: ChunkRepository,
    db_session: AsyncSession,
) -> dict[str, Any]:
    """Execute one plan step: permission re-clip, R1b interpolation, vector retrieval.

    State reads:  current_step, past_steps, source_ids, plan, trace_id
    State writes: past_steps (full list with new entry appended), step_event_data
    Does NOT write to retrieved_chunks (step-scoped, not turn-scoped).

    step_event_data is REPLACED (not accumulated) each call — T-058 must consume
    it before the next execute_step invocation.
    """
    current_step: PlanStep | None = state.get("current_step")
    if not current_step:
        logger.error("execute_step: no current_step in state")
        # Return empty step_event_data to clear stale events; past_steps unchanged.
        return {
            "step_event_data": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    step_id: str = current_step["id"]
    source_id: str = current_step["source_id"]
    sub_query: str = current_step["sub_query"]
    step_label: str = current_step["description"]

    # Sanitize LLM-generated identifiers for safe logging (Security Rule 1)
    step_id_log = _safe_log(step_id)
    source_id_log = _safe_log(source_id)

    plan: list[PlanStep] = list(state.get("plan") or [])
    past_steps: list[dict] = list(state.get("past_steps") or [])
    permitted_ids: list[str] = list(state.get("source_ids") or [])

    total_steps = len(plan)
    step_idx = next((i for i, s in enumerate(plan) if s["id"] == step_id), 0)
    if not any(s["id"] == step_id for s in plan):
        logger.warning("execute_step: step=%s not found in plan — progress may be inaccurate", step_id_log)
    current_step_num = step_idx + 1

    events: list[dict[str, Any]] = []
    in_tok = 0
    out_tok = 0
    span = None

    try:
        span = langfuse.span(
            trace_id=state.get("trace_id", ""),
            name="execute_step",
            input={"step_id": step_id, "source_id": source_id},
        )

        # Guard: permission re-clip (FR-009)
        if source_id not in permitted_ids:
            logger.warning(
                "execute_step: permission DENIED step=%s — source not in permitted set",
                step_id_log,
            )
            fail_event = _step_event(
                step_id=step_id,
                label=step_label,
                state_name="failed",
                summary="Step could not be completed: source access denied.",
                current=current_step_num,
                total=total_steps,
            )
            events.append(fail_event)
            span.update(output={"result": "permission_denied"})
            result = StepResult(
                step_id=step_id,
                output_chunks=[],
                generated_sql=None,
                bound_inputs=None,
                verification=_Verification(
                    verdict="unacceptable",
                    reason="Permission denied: source not in permitted set.",
                    checks={},
                ),
                narration="Step failed: source access denied.",
            )
            return {
                "past_steps": [*past_steps, result],
                "step_event_data": events,
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
            }

        # Emit started event
        started_event = _step_event(
            step_id=step_id,
            label=step_label,
            state_name="started",
            summary=None,
            current=current_step_num,
            total=total_steps,
        )
        events.append(started_event)

        # R1b: resolve {{sN.output}} references deterministically
        resolved_query, bound_inputs = _interpolate(sub_query, past_steps)

        # Cap resolved_query to avoid exceeding embedding API token limits (H-3)
        if len(resolved_query) > _MAX_RESOLVED_QUERY_CHARS:
            logger.warning(
                "execute_step: step=%s resolved_query truncated from %d to %d chars",
                step_id_log,
                len(resolved_query),
                _MAX_RESOLVED_QUERY_CHARS,
            )
            resolved_query = resolved_query[:_MAX_RESOLVED_QUERY_CHARS]

        # Load step-scoped schema context (non-empty for DB sources with a study)
        schema_chunks: list[dict[str, Any]] = await load_schema_context_chunks(
            db_session,
            source_ids=[source_id],
        )

        # Vector retrieval: embed resolved_query, scope to step's source_id
        embedding_service, active_id = await embedding_service_factory.for_active()
        query_embedding = await embedding_service.embed_query(resolved_query)
        raw_results = await chunk_repository.similarity_search(
            db_session,
            query_embedding=query_embedding,
            source_ids=[source_id],
            limit=_SIMILARITY_LIMIT,
            embedder_id=active_id,
        )

        vector_chunks: list[dict[str, Any]] = [
            {
                "chunk_id": str(chunk.id),
                "source_id": str(chunk.source_id),
                "text": chunk.chunk_text,
                "score": round(float(score), 4),
                "document_title": (chunk.metadata_ or {}).get("document_title"),
                "page_number": (chunk.metadata_ or {}).get("page_number"),
                "source_name": (chunk.metadata_ or {}).get("source_name"),
            }
            for chunk, score in raw_results
        ]

        # Schema chunks first (deterministic grounding), then vector hits
        output_chunks: list[dict[str, Any]] = [*schema_chunks, *vector_chunks]

        narration = _narrate(output_chunks)
        result = StepResult(
            step_id=step_id,
            output_chunks=output_chunks,
            generated_sql=None,
            bound_inputs=bound_inputs,
            verification=_Verification(
                verdict="partial",  # placeholder — T-054 verifier overwrites
                reason="pending",
                checks={},
            ),
            narration=narration,
        )

        finished_event = _step_event(
            step_id=step_id,
            label=step_label,
            state_name="finished",
            summary=narration,
            current=current_step_num,
            total=total_steps,
        )
        events.append(finished_event)

        span.update(
            output={
                "result": "success",
                "n_chunks": len(output_chunks),
                "bound_inputs_truncated": bound_inputs["truncated"] if bound_inputs else False,
            }
        )
        logger.info(
            "execute_step: step=%s source=%s chunks=%d",
            step_id_log,
            source_id_log,
            len(output_chunks),
        )
        return {
            "past_steps": [*past_steps, result],
            "step_event_data": events,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    except Exception:
        logger.error("execute_step: step=%s failed", step_id_log, exc_info=True)
        fail_event = _step_event(
            step_id=step_id,
            label=step_label,
            state_name="failed",
            summary="Step failed due to an internal error.",
            current=current_step_num,
            total=total_steps,
        )
        events.append(fail_event)
        error_result = StepResult(
            step_id=step_id,
            output_chunks=[],
            generated_sql=None,
            bound_inputs=None,
            verification=_Verification(
                verdict="unacceptable",
                reason="Step failed due to internal error.",
                checks={},
            ),
            narration="Step failed.",
        )
        if span is not None:
            span.update(output={"result": "error"})
        return {
            "past_steps": [*past_steps, error_result],
            "step_event_data": events,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
        }

    finally:
        if span is not None:
            span.end()
