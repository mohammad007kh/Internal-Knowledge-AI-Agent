"""Celery task: propose draft source intent from a studied DB schema (T-022).

After a database source is studied, the system can infer two of the four
intent fields the source-router consumes — ``example_questions`` and
``out_of_scope`` — from the persisted :class:`SchemaDocument`. This task
builds those drafts via a cheap-tier LLM call, sanitises the output, and
writes it via the TOCTOU-safe bundle-level conditional update so a
concurrent admin save always wins.

Fires on two lifecycle events:

* ``POST /api/v1/sources/{source_id}/intent/propose`` (T-023) — the
  guaranteed entry point, enqueues this task and returns ``202``.
* Chained off a successful schema study (see
  :mod:`src.tasks.study_source`'s completion path), mirroring how
  ``auto_name_source`` chains off sync success.

Pipeline (:func:`_run`):

1. Load the source; if ``intent_status == 'user_set'`` → short-circuit
   ``"skipped"`` (no LLM call). ``user_set`` is terminal for AI writes.
2. Load the latest completed :class:`SchemaDocument`; if none →
   ``"skipped"`` (nothing to infer from yet).
3. Resolve a cheap-tier LLM slot from the class-level container, build a
   prompt over a compact schema projection, and call it **Langfuse-traced**
   (Constitution II — LLM Observability).
4. Parse the structured output into candidate ``example_questions`` (≤5)
   and ``out_of_scope`` (≤10).
5. Sanitise the candidates in LENIENT mode (T-021) — instruction-like
   items are silently dropped and the caps enforced.
6. Persist via :meth:`SourceRepository.propose_intent_conditional`
   (T-020), which writes ONLY ``example_questions`` + ``out_of_scope``
   (NEVER ``purpose`` / ``cross_source_hints``) guarded by
   ``WHERE intent_status != 'user_set'``.
7. Return a small status dict (``"ai_set"`` / ``"skipped"``).

Idempotency mirrors :mod:`auto_name_source`: the ``user_set``
short-circuit and the conditional UPDATE together mean a duplicate enqueue
produces at most one durable write, and a concurrent admin save is never
clobbered.

Retries: ``autoretry_for=(Exception,)`` with exponential backoff up to
three attempts, same policy as ``auto_name_source``.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.database import AsyncSessionLocal
from src.prompts import load_prompt
from src.repositories.source_repository import (
    INTENT_STATUS_USER_SET,
    SourceRepository,
)
from src.services.intent_sanitizer import (
    sanitize_out_of_scope,
    sanitize_question_list,
)
from src.tasks import celery_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cheap-tier slot used for the proposal call (Constitution II: a cheap slot,
# Langfuse-traced). ``retrieval_grader`` (T-012) is a cold/deterministic
# short-output slot — exactly the cheap tier this draft step wants. The
# prompt + trace use a dedicated ``intent_proposal`` name so this task does
# not clobber the grader's own prompt; the resolver slot stays ``retrieval_grader``.
_RESOLVER_STAGE: str = "retrieval_grader"
_PROMPT_NAME: str = "intent_proposal"
_LANGFUSE_TRACE_NAME: str = "intent_proposal"

# How much of the schema projection we forward into the prompt. Caps keep the
# cheap slot's token budget bounded regardless of how wide the source is.
_MAX_TABLES_IN_PROMPT: int = 40
_MAX_COLUMNS_PER_TABLE: int = 20
_MAX_SUMMARY_CHARS: int = 1_000


# ---------------------------------------------------------------------------
# Structured-output contract
# ---------------------------------------------------------------------------


class _IntentProposalPayload(BaseModel):
    """Strict shape for the LLM's JSON response.

    ``extra="forbid"`` so a chatty model that adds keys fails fast at the
    type boundary rather than smuggling unvalidated text downstream. The
    lists are defaulted so a model that omits a field yields an empty draft
    for it rather than raising.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    example_questions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "intent_proposal_payload",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["example_questions", "out_of_scope"],
            "properties": {
                "example_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "out_of_scope": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IntentProposalError(RuntimeError):
    """Raised when the proposal LLM call fails or returns an unusable payload.

    The Celery wrapper owns retry policy (``autoretry_for=(Exception,)``);
    raising a domain exception keeps the failure mode unambiguous in logs
    and Langfuse traces.
    """


# ---------------------------------------------------------------------------
# Public Celery task
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="tasks.propose_intent",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def propose_intent(self: Any, source_id: str) -> dict[str, Any]:
    """Celery entry point. Sync wrapper around :func:`_run` so we play well
    with Celery's process-pool worker (no running event loop by default)."""
    import asyncio  # noqa: PLC0415

    return asyncio.run(_run(uuid.UUID(source_id)))


# ---------------------------------------------------------------------------
# Async core — directly callable from unit tests
# ---------------------------------------------------------------------------


async def _run(source_id: uuid.UUID) -> dict[str, Any]:
    """Build an intent draft from the latest schema doc and persist it.

    Returns a small status dict for the Celery result backend / Langfuse.
    """
    async with AsyncSessionLocal() as session:
        source_repo = SourceRepository(session)

        intent = await source_repo.get_intent(source_id)
        if intent.get("intent_status") == INTENT_STATUS_USER_SET:
            logger.info(
                "propose_intent: source %s intent is user_set — skipping "
                "(no LLM call)",
                source_id,
            )
            return {"source_id": str(source_id), "status": "skipped"}

        schema_document = await _load_latest_schema_document(session, source_id)
        if schema_document is None:
            logger.info(
                "propose_intent: source %s has no completed schema doc — "
                "skipping",
                source_id,
            )
            return {"source_id": str(source_id), "status": "skipped"}

        candidate = await _propose_from_schema(schema_document, source_id=source_id)

        # Security rule 1 — sanitise the LLM output (LENIENT mode) BEFORE it
        # ever reaches the repository. Instruction-like items are dropped and
        # the caps enforced; a partially-bad draft still yields value.
        example_questions = sanitize_question_list(
            candidate.example_questions, strict=False
        )
        out_of_scope = sanitize_out_of_scope(candidate.out_of_scope, strict=False)

        # Bundle-level conditional UPDATE (T-020) — writes ONLY the two
        # AI-writable fields, guarded by ``intent_status != 'user_set'``.
        # NEVER pass purpose / cross_source_hints.
        updated = await source_repo.propose_intent_conditional(
            source_id,
            example_questions=example_questions,
            out_of_scope=out_of_scope,
        )

        if not updated:
            # 0 rows affected: the source is gone, or a concurrent admin save
            # flipped intent_status to user_set after our initial read (TOCTOU
            # race lost). Nothing was written, so there is nothing to commit —
            # we skip the commit and short-circuit.
            logger.info(
                "propose_intent: conditional update affected 0 rows for source "
                "%s — admin save won the race or source removed",
                source_id,
            )
            return {"source_id": str(source_id), "status": "skipped"}

        await session.commit()

    logger.info(
        "propose_intent: completed",
        extra={
            "source_id": str(source_id),
            "example_question_count": len(example_questions),
            "out_of_scope_count": len(out_of_scope),
        },
    )
    return {
        "source_id": str(source_id),
        "status": "ai_set",
        "example_question_count": len(example_questions),
        "out_of_scope_count": len(out_of_scope),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_latest_schema_document(
    session: AsyncSession, source_id: uuid.UUID
) -> Any | None:
    """Return the latest completed :class:`SchemaDocument`, or ``None``.

    Reuses :meth:`SourceRepository.get_latest_completed_study` (the same
    read the admin schema-viewer uses) and re-validates the persisted JSON
    back into a :class:`SchemaDocument` so the projection helper works
    against the strict model rather than a raw dict. A missing study, a
    study without a document, or a malformed document all collapse to
    ``None`` — the caller treats that as a clean "nothing to propose" skip.
    """
    from src.services.db_introspection.schema_doc import (  # noqa: PLC0415
        SchemaDocument,
    )

    study = await SourceRepository(session).get_latest_completed_study(source_id)
    if study is None:
        return None
    doc_json = getattr(study, "schema_document_json", None)
    if not doc_json:
        return None
    try:
        return SchemaDocument.model_validate(doc_json)
    except ValidationError:
        logger.warning(
            "propose_intent: persisted schema document for source %s failed "
            "validation — skipping proposal",
            source_id,
            exc_info=True,
        )
        return None


async def _propose_from_schema(
    schema_document: Any, *, source_id: uuid.UUID
) -> _IntentProposalPayload:
    """Call the cheap-tier LLM slot to draft intent from the schema doc.

    Resolves the slot from the class-level container (same singleton the
    FastAPI process uses — see ``auto_name_source._build_profiler_factory``
    for why constructing a fresh ``Container()`` here would leak HTTP
    pools), builds the prompt over a compact projection, and wraps the call
    in a Langfuse span (Constitution II). Wraps any failure in
    :class:`IntentProposalError` so the Celery retry policy owns it.
    """
    resolver = _build_ai_model_resolver()
    langfuse = _build_langfuse()

    client = await resolver.resolve(_RESOLVER_STAGE)
    prompt = load_prompt(_PROMPT_NAME, custom=client.custom_prompt)
    user_payload = _build_user_payload(schema_document)

    span = langfuse.span(
        name=_LANGFUSE_TRACE_NAME,
        input={
            "source_id": str(source_id),
            "dialect": getattr(schema_document, "dialect", None),
            "table_count": len(getattr(schema_document, "tables", []) or []),
        },
    )
    try:
        try:
            response = await client.http_client.chat.completions.create(
                model=client.model_id,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_payload},
                ],
                temperature=client.temperature,
                max_tokens=client.max_tokens,
                response_format=_RESPONSE_FORMAT,
            )
        except Exception as exc:  # noqa: BLE001 - wrapped into domain error
            logger.warning(
                "propose_intent: LLM call failed",
                extra={"source_id": str(source_id)},
                exc_info=True,
            )
            raise IntentProposalError(
                f"intent_proposal LLM call failed: {exc}"
            ) from exc

        raw = _extract_content(response, source_id=source_id)
        payload = _parse_payload(raw, source_id=source_id)
        span.update(
            output={
                "example_question_count": len(payload.example_questions),
                "out_of_scope_count": len(payload.out_of_scope),
            }
        )
        return payload
    finally:
        span.end()


def _build_ai_model_resolver() -> Any:
    """Resolve the :class:`AIModelResolver` singleton from the container.

    Class-level access returns the same singleton the FastAPI process uses;
    constructing a fresh ``Container()`` would build a new resolver (and new
    HTTP pools) on every task invocation. Mirrors
    ``auto_name_source._build_profiler_factory``.
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.ai_model_resolver()


def _build_langfuse() -> Any:
    """Resolve the Langfuse client singleton from the container.

    Returns the shared client (or the :class:`NullLangfuse` no-op stub when
    credentials are absent) — same singleton the chat pipeline traces into.
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.langfuse()


def _build_user_payload(schema_document: Any) -> str:
    """Serialise a compact, bounded projection of the schema for the prompt.

    We forward only what the model needs to draft questions/out-of-scope:
    the dialect, the corpus summary, and a capped table list (name +
    description + column names). Native types, sample values, indexes, and
    relationships are intentionally omitted — they bloat the token budget
    without helping the draft. Caps keep the prompt bounded regardless of
    how wide the source is.
    """
    summary = (getattr(schema_document, "summary", "") or "")[:_MAX_SUMMARY_CHARS]
    tables_raw = list(getattr(schema_document, "tables", []) or [])

    tables: list[dict[str, Any]] = []
    for table in tables_raw[:_MAX_TABLES_IN_PROMPT]:
        columns = [
            getattr(col, "name", "")
            for col in (getattr(table, "columns", []) or [])[
                :_MAX_COLUMNS_PER_TABLE
            ]
        ]
        tables.append(
            {
                "name": getattr(table, "name", ""),
                "description": getattr(table, "description", "") or "",
                "columns": columns,
            }
        )

    return json.dumps(
        {
            "dialect": getattr(schema_document, "dialect", None),
            "summary": summary,
            "tables": tables,
        },
        ensure_ascii=False,
    )


def _extract_content(response: Any, *, source_id: uuid.UUID) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        logger.warning(
            "propose_intent: LLM response missing content",
            extra={"source_id": str(source_id)},
        )
        raise IntentProposalError(
            f"intent_proposal: LLM response missing content field: {exc}"
        ) from exc


def _parse_payload(raw: str, *, source_id: uuid.UUID) -> _IntentProposalPayload:
    if not raw or not raw.strip():
        raise IntentProposalError("intent_proposal: LLM returned empty content")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "propose_intent: LLM returned non-JSON content",
            extra={"source_id": str(source_id)},
        )
        raise IntentProposalError(
            f"intent_proposal: LLM returned non-JSON content: {exc}"
        ) from exc
    try:
        return _IntentProposalPayload.model_validate(data)
    except ValidationError as exc:
        logger.warning(
            "propose_intent: LLM payload failed strict validation",
            extra={"source_id": str(source_id)},
        )
        raise IntentProposalError(
            f"intent_proposal: malformed payload: {exc}"
        ) from exc
