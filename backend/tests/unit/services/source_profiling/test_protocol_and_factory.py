"""Tests for the SourceProfiler protocol contract + factory dispatch.

These tests don't exercise any concrete profiler — they verify that the
Protocol + Pydantic model + factory dispatch behave correctly so that
F4-F6 implementations can rely on them.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest

from src.models.enums import SourceType
from src.models.source import Source
from src.services.source_profiling import (
    SourceProfile,
    SourceProfiler,
    SourceProfilerFactory,
)


class _FakeProfiler:
    """Minimal stand-in for a real profiler — only used to exercise the
    factory dispatch and protocol shape."""

    source_types: ClassVar[set[SourceType]] = {SourceType.FILE_UPLOAD}

    def __init__(self, label: str = "fake") -> None:
        self._label = label

    async def profile(self, source: Source, db: object) -> SourceProfile:  # type: ignore[override]
        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=[self._label],
            entities=[],
            content_types=[],
            coverage_summary=f"profiled by {self._label}",
            scope_exclusions="",
            sample_count=0,
        )


class _DatabaseFakeProfiler(_FakeProfiler):
    source_types: ClassVar[set[SourceType]] = {SourceType.DATABASE}


def _make_source(source_type: SourceType) -> Source:
    """Construct a transient Source instance — no DB session needed because
    the factory only reads ``source_type``."""
    s = Source(
        name="test",
        source_type=source_type,
        owner_id=uuid.uuid4(),
        is_active=False,
    )
    s.id = uuid.uuid4()
    return s


def test_source_profile_is_strict_and_frozen() -> None:
    """extra='forbid' rejects unknown keys; frozen=True rejects mutation."""
    profile = SourceProfile(
        source_id=str(uuid.uuid4()),
        source_type=SourceType.FILE_UPLOAD,
        coverage_summary="x",
    )
    with pytest.raises(ValueError):
        SourceProfile(
            source_id=str(uuid.uuid4()),
            source_type=SourceType.FILE_UPLOAD,
            coverage_summary="x",
            unknown_field="oops",
        )
    with pytest.raises(ValueError):
        # Frozen — Pydantic raises on set-attribute.
        profile.coverage_summary = "y"  # type: ignore[misc]


def test_source_profile_accepts_minimal_payload() -> None:
    """The only required fields are source_id, source_type, coverage_summary.
    Everything else has a sensible default."""
    profile = SourceProfile(
        source_id="abc",
        source_type=SourceType.WEB_URL,
        coverage_summary="empty source — no content yet",
    )
    assert profile.topics == []
    assert profile.entities == []
    assert profile.content_types == []
    assert profile.scope_exclusions == ""
    assert profile.sample_count == 0


def test_factory_dispatches_to_registered_profiler() -> None:
    factory = SourceProfilerFactory()
    fake_files = _FakeProfiler("files")
    fake_db = _DatabaseFakeProfiler("db")
    factory.register_profiler(fake_files)
    factory.register_profiler(fake_db)

    file_source = _make_source(SourceType.FILE_UPLOAD)
    db_source = _make_source(SourceType.DATABASE)

    assert factory.for_source(file_source) is fake_files
    assert factory.for_source(db_source) is fake_db


def test_factory_raises_lookup_error_for_unregistered_type() -> None:
    factory = SourceProfilerFactory()
    factory.register_profiler(_FakeProfiler())

    with pytest.raises(LookupError, match="No SourceProfiler registered"):
        factory.for_source(_make_source(SourceType.WEB_URL))


def test_factory_rejects_double_registration_for_same_type() -> None:
    factory = SourceProfilerFactory()
    factory.register_profiler(_FakeProfiler("first"))
    with pytest.raises(ValueError, match="already registered"):
        # Different instance, same source_types — silent override would
        # be a footgun; the factory raises so the misconfiguration is loud.
        factory.register_profiler(_FakeProfiler("second"))


def test_factory_idempotent_for_same_instance() -> None:
    """Re-registering the SAME profiler instance is a no-op (legit on
    container reload), distinct from the double-register error above."""
    factory = SourceProfilerFactory()
    p = _FakeProfiler()
    factory.register_profiler(p)
    factory.register_profiler(p)  # should not raise
    assert factory.for_source(_make_source(SourceType.FILE_UPLOAD)) is p


def test_factory_reports_registered_types() -> None:
    factory = SourceProfilerFactory()
    factory.register_profiler(_FakeProfiler())
    factory.register_profiler(_DatabaseFakeProfiler())
    assert factory.registered_types == frozenset(
        {SourceType.FILE_UPLOAD, SourceType.DATABASE}
    )


def test_fake_profiler_satisfies_protocol() -> None:
    """Runtime-checkable Protocol — verifies that any class with the right
    shape passes isinstance() so __init__ wiring can lean on it."""
    assert isinstance(_FakeProfiler(), SourceProfiler)
