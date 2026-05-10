"""SourceProfiler Protocol + SourceProfile Pydantic model.

A *profile* is a structured, source-type-agnostic summary of what's in a
configured source. The :class:`SourceProfile` shape is what the downstream
:class:`~src.services.source_naming_service.SourceNamingService` reads to
write a name + retrieval-friendly description for the source.

Each source type implements its own :class:`SourceProfiler` so the
exploration pre-step is appropriate for the data:

* DB sources reuse the studying agent's :class:`SchemaDocument` (no new LLM
  cost — schema already explored).
* File sources sample chunks across position with a single LLM call
  ("file exploration agent").
* Web URL sources read the parsed page tree.
* Connector sources sample the first sync's document tree.

The naming step is shared — every profiler's output funnels through one
prompt, one Langfuse trace, one structured-output schema.

Strict-mode Pydantic v2 (``extra="forbid"``) — same convention as
:class:`~src.services.db_introspection.schema_doc.SchemaDocument`. Drift
between this contract and any profiler implementation fails fast.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SourceType
from src.models.source import Source


class _StrictModel(BaseModel):
    """Base for every profile model — forbid unknown keys, freeze instances."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceProfile(_StrictModel):
    """Structured profile of a configured source.

    The fields are intentionally narrow. Every field is something a downstream
    LLM call needs to write a useful name + a router-friendly description.
    Adding a field is a deliberate contract change — update both the
    Profilers and the SourceNamingService prompt template together.
    """

    source_id: str = Field(
        ...,
        description="UUID of the Source the profile was built for.",
    )
    source_type: SourceType = Field(
        ...,
        description="Canonical source type at profile build time.",
    )
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "3-8 short noun phrases describing what's in this source. "
            "Used by the naming prompt to coerce 'Covers: …' phrasing."
        ),
    )
    entities: list[str] = Field(
        default_factory=list,
        description=(
            "Named entities the source repeatedly references — product names, "
            "team names, customer names, table names, page titles, etc. Helps "
            "the source-router match user questions that mention them."
        ),
    )
    content_types: list[str] = Field(
        default_factory=list,
        description=(
            "Modalities / formats present in the source — 'spreadsheet rows', "
            "'API reference pages', 'meeting notes', 'database tables', etc. "
            "Free-form short labels, max ~5."
        ),
    )
    coverage_summary: str = Field(
        ...,
        max_length=600,
        description=(
            "One-paragraph plain-English summary of what's in here. The "
            "naming prompt feeds this in as the seed for the final "
            "description's first sentence."
        ),
    )
    scope_exclusions: str = Field(
        default="",
        max_length=200,
        description=(
            "Short note describing what's NOT in this source so the "
            "source-router can rule it out for off-topic questions. "
            "Empty string means the profiler couldn't determine scope."
        ),
    )
    sample_count: int = Field(
        default=0,
        ge=0,
        description=(
            "How many discrete units (chunks / tables / pages) the profiler "
            "looked at to build this profile — useful for telemetry and for "
            "the LLM call's confidence calibration."
        ),
    )


@runtime_checkable
class SourceProfiler(Protocol):
    """Protocol every per-source-type profiler implements.

    Implementations live in
    :mod:`src.services.source_profiling.{database,file,web,connector}_profiler`
    and are dispatched by :class:`SourceProfilerFactory`. Mirror the
    ``ConnectorFactory`` pattern: each profiler declares which
    :class:`SourceType` values it handles via ``source_types``.
    """

    source_types: ClassVar[set[SourceType]]

    async def profile(self, source: Source, db: AsyncSession) -> SourceProfile:
        """Inspect the source and build a structured profile.

        Implementations MUST:

        * Be idempotent — calling twice on the same source produces equivalent
          profiles modulo wall-clock-tied fields.
        * Never include sample row values for DB sources without an explicit
          admin opt-in (PII safety).
        * Never raise on empty data — return a profile with empty topics /
          entities and a ``coverage_summary`` that says "no content yet" so
          the naming step can fall back to a placeholder name without
          crashing the worker.

        Args:
            source: The persisted :class:`~src.models.source.Source` row.
            db: Active request-scoped session — passed through so profilers
                can query related rows (chunks, schema_studies, sync_jobs)
                without spinning up their own session.

        Returns:
            A frozen :class:`SourceProfile`.
        """
        ...
