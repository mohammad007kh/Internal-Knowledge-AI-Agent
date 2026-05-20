"""DatabaseSourceProfiler — projects an existing :class:`SchemaDocument`
into a :class:`SourceProfile`.

The studying agent (Phase 1 Wave 1) already explored the database — table
names, columns, agent-authored table descriptions, FK relationships are
all on the latest :class:`SchemaStudy` row. We just shape that data into
the source-type-agnostic :class:`SourceProfile` the naming step consumes.

**No new LLM call.** No row samples. Schema-only — see ``memory/constitution.md``
on PII safety for DB sources. The naming step that comes after this profile
is what actually invokes the LLM (with this profile as input).

When a source has no SchemaStudy yet (the studying agent hasn't run, or it
failed), the profiler returns a near-empty profile so the naming pipeline
can still pick a sensible placeholder name without crashing.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SourceType
from src.models.schema_study import SchemaStudy
from src.models.source import Source
from src.services.db_introspection.schema_doc import SchemaDocument, TableDoc
from src.services.source_profiling.protocol import SourceProfile

logger = logging.getLogger(__name__)


# Cap how much detail we surface in the profile.  Past these limits the LLM
# downstream stops paying attention and starts hallucinating; trimming up
# front keeps the naming prompt deterministic regardless of DB size.
_MAX_TOPICS = 8
_MAX_ENTITIES = 12
_MAX_TABLES_FOR_SUMMARY = 30


class DatabaseSourceProfiler:
    """Profiler for SQL + MongoDB sources — reads the studying agent's output."""

    source_types: ClassVar[set[SourceType]] = {SourceType.DATABASE}

    async def profile(self, source: Source, db: AsyncSession) -> SourceProfile:
        latest_study = await self._latest_completed_study(source, db)

        if latest_study is None or latest_study.schema_document_json is None:
            logger.info(
                "DatabaseSourceProfiler: no SchemaStudy yet — emitting empty profile",
                extra={"source_id": str(source.id)},
            )
            return self._empty_profile(source)

        try:
            doc = SchemaDocument.model_validate(latest_study.schema_document_json)
        except Exception:  # noqa: BLE001 — bad JSON shape is recoverable
            logger.warning(
                "DatabaseSourceProfiler: schema_document_json failed strict "
                "validation — emitting empty profile",
                extra={"source_id": str(source.id)},
                exc_info=True,
            )
            return self._empty_profile(source)

        return self._project(source, doc)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _latest_completed_study(
        self, source: Source, db: AsyncSession
    ) -> SchemaStudy | None:
        """Return the most recent SchemaStudy whose schema_document_json is
        populated. We deliberately don't filter on ``state`` because the
        document can be present on READY *and* READY_PARTIAL — the partial
        flag is encoded inside the document itself."""
        stmt = (
            select(SchemaStudy)
            .where(SchemaStudy.source_id == source.id)
            .where(SchemaStudy.schema_document_json.is_not(None))
            .order_by(SchemaStudy.finished_at.desc().nulls_last())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _empty_profile(self, source: Source) -> SourceProfile:
        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=[],
            entities=[],
            content_types=["database tables"],
            coverage_summary=(
                "Database source — schema not yet documented. The studying "
                "agent will populate this profile once it completes."
            ),
            scope_exclusions="",
            sample_count=0,
        )

    def _project(self, source: Source, doc: SchemaDocument) -> SourceProfile:
        tables = doc.tables or []
        considered = tables[:_MAX_TABLES_FOR_SUMMARY]

        topics = self._derive_topics(considered)
        entities = self._derive_entities(considered)
        content_types = self._derive_content_types(doc)
        coverage_summary = self._coverage_summary(doc, considered)
        scope_exclusions = self._scope_exclusions(doc, tables)

        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=topics,
            entities=entities,
            content_types=content_types,
            coverage_summary=coverage_summary,
            scope_exclusions=scope_exclusions,
            # Sample count is the number of tables we examined — that's the
            # unit of inspection for DB profiling.
            sample_count=len(considered),
        )

    def _derive_topics(self, tables: list[TableDoc]) -> list[str]:
        """Topics are pulled from table tags first (the studying agent's
        own categorisation — 'audit_log', 'transactional', 'lookup', etc.)
        and falls back to fully-qualified table names."""
        seen: dict[str, None] = {}
        for t in tables:
            for tag in t.tags:
                if tag and tag not in seen:
                    seen[tag] = None
                if len(seen) >= _MAX_TOPICS:
                    return list(seen)
        # If tags didn't yield enough variety, append the most-row table names.
        for t in sorted(
            tables,
            key=lambda t: (t.row_count_estimate or 0),
            reverse=True,
        ):
            short = t.name.split(".")[-1]
            if short and short not in seen:
                seen[short] = None
            if len(seen) >= _MAX_TOPICS:
                break
        return list(seen)

    def _derive_entities(self, tables: list[TableDoc]) -> list[str]:
        """Entities are the fully qualified table names — what the
        source-router needs to match against user questions like 'show me
        the orders table' or 'how many invoices are there'."""
        names: list[str] = []
        for t in tables:
            if t.name and t.name not in names:
                names.append(t.name)
            if len(names) >= _MAX_ENTITIES:
                break
        return names

    def _derive_content_types(self, doc: SchemaDocument) -> list[str]:
        labels: list[str] = [f"{doc.dialect} database"]
        kinds = {t.kind for t in doc.tables}
        if "view" in kinds or "materialized_view" in kinds:
            labels.append("views")
        if "collection" in kinds:
            labels.append("document collections")
        if any(t.relationships for t in doc.tables):
            labels.append("relational tables")
        return labels

    def _coverage_summary(
        self, doc: SchemaDocument, considered: list[TableDoc]
    ) -> str:
        """Use the studying agent's own corpus-level summary if present;
        otherwise synthesise from table count + dialect."""
        if doc.summary.strip():
            # Truncate to the SourceProfile field cap (600).
            return doc.summary.strip()[:600]
        table_count = len(doc.tables)
        if table_count == 0:
            return f"Empty {doc.dialect} database — no tables documented."
        described = sum(1 for t in considered if t.description.strip())
        return (
            f"{doc.dialect.capitalize()} database with {table_count} "
            f"documented tables/collections "
            f"({described} with table-level descriptions)."
        )[:600]

    def _scope_exclusions(
        self, doc: SchemaDocument, all_tables: list[TableDoc]
    ) -> str:
        """When a study was partial we surface that as a scope exclusion so
        the source-router doesn't over-trust the description for the parts
        of the schema that weren't documented."""
        if doc.partial:
            failed_phases = sorted({pe.phase for pe in doc.phase_errors})
            phase_str = ", ".join(failed_phases) if failed_phases else "some phases"
            return (
                f"Partial documentation — {phase_str} did not complete; "
                "ask carefully about tables not listed above."
            )[:200]
        if len(all_tables) > _MAX_TABLES_FOR_SUMMARY:
            extra = len(all_tables) - _MAX_TABLES_FOR_SUMMARY
            return (
                f"Profile was truncated — {extra} additional tables exist "
                "in the schema but were not surfaced here."
            )[:200]
        return ""
