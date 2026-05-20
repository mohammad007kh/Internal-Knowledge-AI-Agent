"""SourceProfilerFactory — dispatches a Source to the right profiler.

Mirrors the :class:`~src.connectors.factory.ConnectorFactory` pattern:
each concrete :class:`~src.services.source_profiling.protocol.SourceProfiler`
implementation declares the :class:`~src.models.enums.SourceType` values it
handles via the ``source_types`` ClassVar; the factory builds a registry from
that and resolves at runtime.

Adding a new profiler is two lines: implement the protocol, register the
class via :func:`register_profiler`. No central enum-to-class map to keep in
sync.
"""

from __future__ import annotations

import logging

from src.models.enums import SourceType
from src.models.source import Source
from src.services.source_profiling.protocol import SourceProfiler

logger = logging.getLogger(__name__)


class SourceProfilerFactory:
    """Resolve the right :class:`SourceProfiler` for a given Source."""

    def __init__(self) -> None:
        self._registry: dict[SourceType, SourceProfiler] = {}

    def register_profiler(self, profiler: SourceProfiler) -> None:
        """Register *profiler* for every :class:`SourceType` in
        ``profiler.source_types``.

        Raises:
            ValueError: if any source_type is already claimed by a different
                profiler — silent overrides are a footgun for the auto-naming
                pipeline.
        """
        for source_type in profiler.source_types:
            existing = self._registry.get(source_type)
            if existing is not None and existing is not profiler:
                raise ValueError(
                    f"SourceType {source_type.value!r} is already registered "
                    f"to {type(existing).__name__}; cannot also register "
                    f"{type(profiler).__name__}."
                )
            self._registry[source_type] = profiler

    def for_source(self, source: Source) -> SourceProfiler:
        """Return the profiler registered for ``source.source_type``.

        Raises:
            LookupError: if no profiler is registered for the source's type.
                Callers should treat this as a hard configuration error and
                NOT silently skip auto-naming.
        """
        # Source.source_type is a SourceType enum member after ORM hydration,
        # but defensively coerce in case a plain string slips through (e.g.
        # from a freshly-built object pre-flush).
        source_type = (
            source.source_type
            if isinstance(source.source_type, SourceType)
            else SourceType(source.source_type)
        )
        try:
            profiler = self._registry[source_type]
        except KeyError as exc:
            raise LookupError(
                f"No SourceProfiler registered for source_type={source_type.value!r}. "
                f"Known types: {sorted(t.value for t in self._registry)}"
            ) from exc
        logger.debug(
            "SourceProfilerFactory.for_source source_id=%s source_type=%s "
            "profiler=%s",
            source.id,
            source_type.value,
            type(profiler).__name__,
        )
        return profiler

    @property
    def registered_types(self) -> frozenset[SourceType]:
        """Set of source types currently covered by a profiler — useful for
        startup health-checks ('do we have a profiler for every SourceType?').
        """
        return frozenset(self._registry)
