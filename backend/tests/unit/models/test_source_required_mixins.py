"""Regression guard: Source MUST inherit every mixin its repositories
depend on.

This bug class has bitten the project twice already:

* Commit ``171612e`` accidentally dropped ``values_callable`` from the
  StrEnum binding while editing the same ``mapped_column``. Symptom: every
  endpoint that loaded a Source row returned 500 with no body, surfacing
  in the browser as a CORS-missing error on /auth/login. Caught only after
  a manual investigation. Regression guard:
  ``tests/unit/models/test_strenum_value_binding.py``.

* Commit ``2f50a16`` (Phase 1 Wave 1A) accidentally dropped
  ``SoftDeleteMixin`` from ``Source`` while editing the imports + class
  signature to add the studying-agent columns. Symptom: every list
  endpoint that joined ``deleted_at IS NULL`` raised
  ``AttributeError: type object 'Source' has no attribute 'deleted_at'``,
  rendering /admin/sources empty. THIS test catches that class.

Both were the same defect class: an edit to ``Source`` silently dropping
something the rest of the codebase relies on. The cheapest defense is an
explicit assertion of the mixins/columns the model owes its callers.
"""

from __future__ import annotations

from src.models.base import SoftDeleteMixin
from src.models.source import Source


def test_source_has_deleted_at_column() -> None:
    """``Source.deleted_at`` is referenced by ~10 sites in
    ``source_repository.py`` and one in ``source_permission_repository.py``.
    Without it every admin list endpoint crashes."""
    assert hasattr(Source, "deleted_at"), (
        "Source.deleted_at is missing — most likely SoftDeleteMixin was "
        "dropped from the class signature. Re-add SoftDeleteMixin to the "
        "import line and the class bases. See "
        "src/models/source.py top of file for the canonical pattern."
    )


def test_source_inherits_soft_delete_mixin() -> None:
    """Belt-and-braces: even if a future column-named-deleted_at survives
    a refactor, the mixin's helper methods (``soft_delete()``,
    ``is_deleted`` property) must be present so the repository's
    ``soft_delete`` calls keep working."""
    assert issubclass(Source, SoftDeleteMixin), (
        "Source must inherit from SoftDeleteMixin. The mixin provides both "
        "the deleted_at column AND the soft_delete() helper. The "
        "repository layer relies on both."
    )


def test_source_has_softdelete_helper_methods() -> None:
    """Calling code uses ``source.soft_delete()`` and the ``is_deleted``
    property. If a future refactor inlines the column without the mixin,
    these would silently disappear."""
    assert hasattr(Source, "soft_delete"), "Source.soft_delete() helper missing"
    assert hasattr(Source, "is_deleted"), "Source.is_deleted property missing"
