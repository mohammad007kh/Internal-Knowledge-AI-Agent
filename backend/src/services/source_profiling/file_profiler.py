"""FileSourceProfiler — explores ingested files via chunk sampling + one LLM call.

This profiler handles two source types that share an identical post-ingestion
shape (Documents -> Chunks rows): :data:`SourceType.FILE_UPLOAD` (admin-uploaded
PDF/DOCX/XLSX/CSV/etc.) and :data:`SourceType.WEB_URL` (scraped pages). Both
land in the same tables, so one profiler covers both.

The exploration strategy: gather a small, representative sample of chunk text
(head / middle / tail per document, capped) plus light file-level metadata
already on the rows, then ask an LLM to describe what's in the corpus. The
LLM call is wrapped in a Langfuse span ``file_profiler`` so traces line up
with the other LLM-driven steps in the auto-naming pipeline.

The decrypted source ``config_encrypted`` is **never** read here — see the
constitution's PII / connector-isolation principle.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk import Chunk
from src.models.document import Document
from src.models.enums import SourceType
from src.models.source import Source
from src.prompts import load_prompt
from src.services.source_profiling.protocol import SourceProfile

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)


# Caps tuned to keep the LLM payload tight. Past these limits we observed
# the LLM ignoring later samples ("lost in the middle") and topic drift —
# trimming up front keeps the profile deterministic regardless of corpus size.
_MAX_DOCS_SAMPLED: int = 8
_MAX_CHUNKS_TOTAL: int = 30
_CHUNKS_PER_DOC: int = 3  # head / middle / tail
_MAX_PAYLOAD_CHARS: int = 4_000  # ~4 KB of chunk text — leaves room in the prompt
_PER_CHUNK_CHAR_BUDGET: int = 600  # truncate any single chunk past this
_RESOLVER_STAGE: str = "source_profiler"
_LANGFUSE_SPAN_NAME: str = "file_profiler"

# MinIO / S3 / filesystem path patterns we strip from chunk text before
# feeding it to the LLM — they're noise, and they leak internal storage
# layout into the trace if we don't.
_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"""
    (?:                              # one of:
        s3a?://[^\s'"]+               #   s3://bucket/key
      | minio://[^\s'"]+              #   minio://...
      | /[A-Za-z0-9_\-./]+            #   absolute POSIX path
      | [a-zA-Z]:\\[\w\-.\\]+         #   absolute Windows path
      | [\w\-]+/[\w\-./]+\.[A-Za-z0-9]{1,5}  # relative path with extension
    )
    """,
    re.VERBOSE,
)


class FileProfilerError(RuntimeError):
    """Raised when the LLM exploration call fails or returns malformed JSON.

    The Celery wrapper around the auto-naming pipeline owns retry policy;
    raising a domain exception here keeps the profiler itself stateless and
    makes the failure mode unambiguous in logs / traces.
    """


class _LLMProfilePayload(BaseModel):
    """Internal strict-mode shape for the LLM's JSON response.

    Mirrors the ``extra='forbid'`` style of :class:`SchemaDocument`: any drift
    between this contract and the prompt template fails fast on validation
    instead of silently corrupting the persisted profile.
    """

    model_config = ConfigDict(extra="forbid")

    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
    coverage_summary: str = Field(default="")
    scope_exclusions: str = Field(default="")


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "file_source_profile",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "topics",
                "entities",
                "content_types",
                "coverage_summary",
                "scope_exclusions",
            ],
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
                "entities": {"type": "array", "items": {"type": "string"}},
                "content_types": {"type": "array", "items": {"type": "string"}},
                "coverage_summary": {"type": "string"},
                "scope_exclusions": {"type": "string"},
            },
        },
    },
}


class FileSourceProfiler:
    """Profiler for any source type that produces Documents + Chunks at
    ingest time — file uploads, web crawls, and the SaaS connectors
    (Confluence, SharePoint). All four feed the same content_chunks table
    so the chunk-sampling + single-LLM-call exploration is identical
    regardless of where the bytes originally came from.

    DATABASE sources have their own profiler because they don't produce
    chunks — see :class:`DatabaseSourceProfiler`.
    """

    source_types: ClassVar[set[SourceType]] = {
        SourceType.FILE_UPLOAD,
        SourceType.WEB_URL,
        SourceType.CONFLUENCE,
        SourceType.SHAREPOINT,
    }

    def __init__(
        self,
        ai_model_resolver: AIModelResolver,
        langfuse: Langfuse,
    ) -> None:
        self._ai_model_resolver = ai_model_resolver
        self._langfuse = langfuse

    async def profile(self, source: Source, db: AsyncSession) -> SourceProfile:
        documents = await self._load_documents(source, db)
        if not documents:
            logger.info(
                "FileSourceProfiler: no documents for source — emitting empty profile",
                extra={"source_id": str(source.id)},
            )
            return self._empty_profile(source)

        samples, total_chunk_count = await self._sample_chunks(documents, db)
        extensions = self._derive_extensions(documents)

        if not samples:
            # Documents exist but somehow no chunk rows yet (rare race: ingest
            # task wrote Documents then died before chunks). Same as no docs.
            logger.info(
                "FileSourceProfiler: %d documents but no chunks — emitting empty profile",
                len(documents),
                extra={"source_id": str(source.id)},
            )
            return self._empty_profile(source)

        payload = await self._call_llm(
            source=source,
            samples=samples,
            doc_count=len(documents),
            total_chunk_count=total_chunk_count,
            extensions=extensions,
        )

        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=payload.topics,
            entities=payload.entities,
            content_types=payload.content_types,
            coverage_summary=(payload.coverage_summary or "")[:600],
            scope_exclusions=(payload.scope_exclusions or "")[:200],
            sample_count=len(samples),
        )

    # ------------------------------------------------------------------ #
    # Sampling                                                            #
    # ------------------------------------------------------------------ #

    async def _load_documents(
        self, source: Source, db: AsyncSession
    ) -> list[Document]:
        """Active documents for the source, ordered by creation time."""
        stmt = (
            select(Document)
            .where(
                Document.source_id == source.id,
                Document.is_active.is_(True),
            )
            .order_by(Document.created_at.asc())
            .limit(_MAX_DOCS_SAMPLED)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _sample_chunks(
        self,
        documents: list[Document],
        db: AsyncSession,
    ) -> tuple[list[str], int]:
        """Return ``(cleaned_samples, total_chunk_count_observed)``.

        For each document we pull head / middle / tail chunk-text excerpts.
        We stop adding samples once :data:`_MAX_CHUNKS_TOTAL` is reached or
        the cumulative payload exceeds :data:`_MAX_PAYLOAD_CHARS`.
        """
        samples: list[str] = []
        total_chunks_seen: int = 0
        budget_used: int = 0

        for doc in documents:
            chunks = await self._chunks_for_document(doc.id, db)
            total_chunks_seen += len(chunks)
            if not chunks:
                continue

            picks = self._pick_head_middle_tail(chunks)
            for c in picks:
                if len(samples) >= _MAX_CHUNKS_TOTAL:
                    return samples, total_chunks_seen
                cleaned = self._clean_chunk_text(c.chunk_text)
                if not cleaned:
                    continue
                if budget_used + len(cleaned) > _MAX_PAYLOAD_CHARS:
                    # Take what fits, then stop — partial chunk beats nothing
                    # for the last slot if there's still meaningful room left.
                    remaining = _MAX_PAYLOAD_CHARS - budget_used
                    if remaining > 80:
                        samples.append(cleaned[:remaining])
                    return samples, total_chunks_seen
                samples.append(cleaned)
                budget_used += len(cleaned)

        return samples, total_chunks_seen

    async def _chunks_for_document(
        self, document_id: Any, db: AsyncSession
    ) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _pick_head_middle_tail(chunks: list[Chunk]) -> list[Chunk]:
        """Pick up to :data:`_CHUNKS_PER_DOC` chunks evenly spaced across the
        document — gives the LLM a representative cross-section without
        biasing toward the beginning (which is often a title page)."""
        if not chunks:
            return []
        if len(chunks) <= _CHUNKS_PER_DOC:
            return list(chunks)
        last_idx = len(chunks) - 1
        middle_idx = last_idx // 2
        # Order matters: head first so even truncated payloads keep the most
        # informative excerpt.
        seen_ix: set[int] = set()
        picks: list[Chunk] = []
        for i in (0, middle_idx, last_idx):
            if i not in seen_ix:
                seen_ix.add(i)
                picks.append(chunks[i])
        return picks

    @staticmethod
    def _clean_chunk_text(text: str) -> str:
        """Strip storage paths, collapse whitespace, truncate to budget."""
        if not text:
            return ""
        cleaned = _PATH_PATTERN.sub("", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > _PER_CHUNK_CHAR_BUDGET:
            cleaned = cleaned[:_PER_CHUNK_CHAR_BUDGET].rstrip() + "…"
        return cleaned

    @staticmethod
    def _derive_extensions(documents: list[Document]) -> list[str]:
        """Distinct lowercase file extensions inferred from
        ``metadata['original_name']`` or ``raw_storage_path``. Best-effort —
        we never crash the profiler on a missing field."""
        seen: dict[str, None] = {}
        for doc in documents:
            candidate: str | None = None
            meta = doc.metadata_ if isinstance(doc.metadata_, dict) else {}
            for key in ("original_name", "filename", "source_url"):
                value = meta.get(key)
                if isinstance(value, str) and value:
                    candidate = value
                    break
            if candidate is None and doc.raw_storage_path:
                candidate = doc.raw_storage_path
            if not candidate:
                continue
            if "." in candidate:
                ext = candidate.rsplit(".", 1)[-1].lower().strip()
                # Strip query strings / fragments leaked from URLs.
                ext = re.split(r"[?#]", ext, maxsplit=1)[0]
                if ext and len(ext) <= 5 and ext.isalnum():
                    seen.setdefault(ext, None)
        return list(seen)

    # ------------------------------------------------------------------ #
    # LLM call                                                            #
    # ------------------------------------------------------------------ #

    async def _call_llm(
        self,
        *,
        source: Source,
        samples: list[str],
        doc_count: int,
        total_chunk_count: int,
        extensions: list[str],
    ) -> _LLMProfilePayload:
        client = await self._ai_model_resolver.resolve(_RESOLVER_STAGE)
        prompt = load_prompt(_RESOLVER_STAGE, custom=client.custom_prompt)
        user_payload = json.dumps(
            {
                "metadata": {
                    "document_count": doc_count,
                    "total_chunk_count": total_chunk_count,
                    "sample_count": len(samples),
                    "file_extensions": extensions,
                },
                "samples": samples,
            },
            ensure_ascii=False,
        )

        span = self._langfuse.span(  # type: ignore[attr-defined]
            name=_LANGFUSE_SPAN_NAME,
            input={
                "source_id": str(source.id),
                "document_count": doc_count,
                "sample_count": len(samples),
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
                    response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
                )
            except Exception as exc:  # noqa: BLE001 - wrapped into domain error
                logger.warning(
                    "FileSourceProfiler: LLM call failed",
                    extra={"source_id": str(source.id)},
                    exc_info=True,
                )
                raise FileProfilerError(
                    f"file_profiler LLM call failed: {exc}"
                ) from exc

            raw = self._extract_content(response)
            payload = self._parse_payload(raw, source_id=str(source.id))
            span.update(  # type: ignore[attr-defined]
                output={
                    "topic_count": len(payload.topics),
                    "entity_count": len(payload.entities),
                }
            )
            return payload
        finally:
            span.end()  # type: ignore[attr-defined]

    @staticmethod
    def _extract_content(response: Any) -> str:
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise FileProfilerError(
                f"file_profiler: LLM response missing content field: {exc}"
            ) from exc

    @staticmethod
    def _parse_payload(raw: str, *, source_id: str) -> _LLMProfilePayload:
        if not raw or not raw.strip():
            raise FileProfilerError("file_profiler: LLM returned empty content")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "FileSourceProfiler: LLM returned non-JSON content",
                extra={"source_id": source_id},
            )
            raise FileProfilerError(
                f"file_profiler: LLM returned non-JSON content: {exc}"
            ) from exc
        try:
            return _LLMProfilePayload.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                "FileSourceProfiler: LLM payload failed strict validation",
                extra={"source_id": source_id},
            )
            raise FileProfilerError(
                f"file_profiler: malformed payload: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Empty / fallback                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _empty_profile(source: Source) -> SourceProfile:
        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=[],
            entities=[],
            content_types=[],
            coverage_summary=(
                "No content yet — source has not finished ingesting."
            ),
            scope_exclusions="",
            sample_count=0,
        )
