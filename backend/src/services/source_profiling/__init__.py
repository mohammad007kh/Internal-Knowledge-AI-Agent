"""Source profiling: per-source-type exploration that feeds the AI auto-naming
pipeline.

Public surface:

* :class:`SourceProfile` — strict Pydantic model the naming step consumes.
* :class:`SourceProfiler` — Protocol every profiler implements.
* :class:`SourceProfilerFactory` — dispatches a Source to the right profiler.

Concrete profilers live in this package as siblings (``database_profiler``,
``file_profiler``, ``web_profiler``, ``connector_profiler``) and are wired
into the DI container at startup.
"""

from src.services.source_profiling.factory import SourceProfilerFactory
from src.services.source_profiling.protocol import SourceProfile, SourceProfiler

__all__ = [
    "SourceProfile",
    "SourceProfiler",
    "SourceProfilerFactory",
]
