"""Registry completeness: every SourceType has a profiler.

A new SourceType added without a profiler would silently break the
auto-naming pipeline at runtime when a Source of that type is created.
This test fails on the bench, not in production.
"""

from __future__ import annotations

from src.models.enums import SourceType
from src.services.source_profiling import SourceProfilerFactory
from src.services.source_profiling.database_profiler import DatabaseSourceProfiler
from src.services.source_profiling.file_profiler import FileSourceProfiler


def _wire_profilers() -> SourceProfilerFactory:
    """Mirror what the DI container does at startup. Real wiring is in
    src.core.containers (or wherever the resolver/langfuse are bound) —
    here we use plain instances because the tests don't call .profile()."""
    factory = SourceProfilerFactory()

    # FileSourceProfiler needs an AIModelResolver + Langfuse for actual calls,
    # but the factory only reads ``.source_types``. None placeholders are
    # safe for this assertion — we never call .profile() in this test.
    factory.register_profiler(FileSourceProfiler(None, None))  # type: ignore[arg-type]
    factory.register_profiler(DatabaseSourceProfiler())
    return factory


def test_every_source_type_has_a_registered_profiler() -> None:
    factory = _wire_profilers()
    missing = set(SourceType) - factory.registered_types
    assert missing == set(), (
        f"SourceType(s) {sorted(t.value for t in missing)} have no registered "
        "profiler. Add a profiler that declares them in its source_types, "
        "or extend an existing profiler. See "
        "src/services/source_profiling/__init__.py for the available implementations."
    )


def test_profilers_dont_overlap() -> None:
    """Two profilers claiming the same SourceType is the bug class
    SourceProfilerFactory.register_profiler raises against. This test
    catches it earlier — at import time."""
    file_types = FileSourceProfiler.source_types
    db_types = DatabaseSourceProfiler.source_types
    overlap = file_types & db_types
    assert overlap == set(), (
        f"FileSourceProfiler and DatabaseSourceProfiler both claim {overlap}. "
        "Pick one."
    )
