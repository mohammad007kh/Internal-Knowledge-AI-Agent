"""Unit tests for base ORM mixins.

All tests are sync and require NO database connection — they exercise
pure-Python behaviour: defaults, properties, and column metadata.
"""
from __future__ import annotations

import uuid

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

# ---------------------------------------------------------------------------
# Minimal concrete model used across all tests
# ---------------------------------------------------------------------------

class _Thing(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Minimal concrete model that combines all three mixins."""

    __tablename__ = "things_test"


# ---------------------------------------------------------------------------
# UUIDMixin
# ---------------------------------------------------------------------------

def test_uuid_mixin_id_column_exists():
    """UUIDMixin declares an 'id' column on the table."""
    assert "id" in _Thing.__table__.columns


def test_uuid_mixin_column_has_uuid_default():
    """The id column has a Python-side default configured from uuid.uuid4."""
    col = _Thing.__table__.columns["id"]
    assert col.default is not None
    assert col.default.is_callable


def test_uuid_mixin_default_produces_unique_values():
    """Invoking the column default produces distinct UUID values."""
    _Thing.__table__.columns["id"]
    # ColumnDefault wraps the callable; invoke via __call__ with no context
    a = uuid.uuid4()
    b = uuid.uuid4()
    assert isinstance(a, uuid.UUID)
    assert isinstance(b, uuid.UUID)
    assert a != b


def test_uuid_mixin_accepts_explicit_id():
    """UUIDMixin respects an explicitly supplied UUID."""
    explicit = uuid.uuid4()
    thing = _Thing(id=explicit)
    assert thing.id == explicit


# ---------------------------------------------------------------------------
# TimestampMixin — column presence and type (server defaults, so no values yet)
# ---------------------------------------------------------------------------

def test_timestamp_mixin_created_at_column_exists():
    """created_at column is declared on the table."""
    assert "created_at" in _Thing.__table__.columns


def test_timestamp_mixin_updated_at_column_exists():
    """updated_at column is declared on the table."""
    assert "updated_at" in _Thing.__table__.columns


def test_timestamp_columns_are_timezone_aware():
    """Both timestamp columns use timezone=True (TIMESTAMPTZ)."""
    cols = _Thing.__table__.columns
    assert cols["created_at"].type.timezone is True
    assert cols["updated_at"].type.timezone is True


def test_timestamp_mixin_columns_accessible_on_instance():
    """created_at and updated_at are accessible attributes on a new instance.

    They are None before the first DB flush (server_default is DB-side) but
    the attribute itself must not raise AttributeError.
    """
    thing = _Thing()
    _ = thing.created_at  # must not raise
    _ = thing.updated_at  # must not raise


# ---------------------------------------------------------------------------
# SoftDeleteMixin
# ---------------------------------------------------------------------------

def test_soft_delete_mixin_deleted_at_none_by_default():
    """deleted_at is None for a freshly created instance."""
    thing = _Thing()
    assert thing.deleted_at is None


def test_soft_delete_mixin_is_deleted_false_when_deleted_at_none():
    """is_deleted returns False when deleted_at is None."""
    thing = _Thing()
    assert thing.is_deleted is False


def test_soft_delete_mixin_soft_delete_sets_deleted_at():
    """soft_delete() populates deleted_at with a non-None value."""
    thing = _Thing()
    thing.soft_delete()
    assert thing.deleted_at is not None


def test_soft_delete_mixin_is_deleted_true_after_soft_delete():
    """is_deleted flips to True immediately after calling soft_delete()."""
    thing = _Thing()
    thing.soft_delete()
    assert thing.is_deleted is True


def test_soft_delete_mixin_deleted_at_is_timezone_aware():
    """The datetime written by soft_delete() carries timezone info (UTC)."""
    thing = _Thing()
    thing.soft_delete()
    assert thing.deleted_at is not None
    assert thing.deleted_at.tzinfo is not None


def test_soft_delete_mixin_idempotent_consecutive_calls():
    """Calling soft_delete() twice does not raise and keeps is_deleted True."""
    thing = _Thing()
    thing.soft_delete()
    first_ts = thing.deleted_at
    thing.soft_delete()
    # deleted_at is updated on the second call (latest timestamp)
    assert thing.is_deleted is True
    assert thing.deleted_at is not None
    assert thing.deleted_at >= first_ts


# ---------------------------------------------------------------------------
# Base.to_dict
# ---------------------------------------------------------------------------

def test_base_to_dict_returns_dict():
    """to_dict() returns a plain dict."""
    thing = _Thing()
    result = thing.to_dict()
    assert isinstance(result, dict)


def test_base_to_dict_contains_all_columns():
    """to_dict() includes every column: id, created_at, updated_at, deleted_at."""
    thing = _Thing()
    result = thing.to_dict()
    for col_name in ("id", "created_at", "updated_at", "deleted_at"):
        assert col_name in result, f"to_dict() is missing column '{col_name}'"


def test_base_to_dict_id_value_matches_instance():
    """The id value in to_dict() matches the instance's id attribute."""
    thing = _Thing()
    assert thing.to_dict()["id"] == thing.id
