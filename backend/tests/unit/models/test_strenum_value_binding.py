"""Regression guard: every ``Enum(StrEnum, ...)`` column in the models layer
MUST set ``values_callable`` so SQLAlchemy binds the lowercase Python value
("file_upload") rather than the uppercase Python name ("FILE_UPLOAD").

The Postgres enum types in this project are created from the StrEnum values,
so an Enum column without values_callable raises:

* ``InvalidTextRepresentationError: invalid input value for enum`` on INSERT
* ``LookupError: '<value>' is not among the defined enum values`` on SELECT

This bug class has bitten us twice already (commits 53de827 and the
171612e regression). This test exists to prevent a third occurrence.
"""

from __future__ import annotations

import enum

import pytest
from sqlalchemy import Enum as SAEnum

# All ORM modules whose models declare Enum-backed columns. Importing the
# package wires every ORM into Base.metadata so we can introspect the columns.
from src.models import (  # noqa: F401  — side-effect imports
    chat,
    connector,
    source,
    sync_job,
    user,
)
from src.models.base import Base


def _strenum_columns_without_values_callable() -> list[str]:
    """Walk every mapped column on every ORM and return offenders."""
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            col_type = column.type
            if not isinstance(col_type, SAEnum):
                continue
            python_enum = col_type.enum_class
            if python_enum is None:
                continue
            # Only StrEnum (and any future str-valued IntEnum-likes) are at
            # risk. Plain enum.Enum classes are unaffected because their
            # values can be anything and SQLAlchemy's default name-binding is
            # unambiguous in that case.
            if not issubclass(python_enum, enum.StrEnum):
                continue
            if col_type.values_callable is None:
                offenders.append(
                    f"{table.name}.{column.name} -> {python_enum.__name__}"
                )
    return offenders


def test_every_strenum_column_uses_values_callable() -> None:
    """Fails loudly if any model declares ``Enum(StrEnum)`` without
    ``values_callable=lambda enum_cls: [m.value for m in enum_cls]``.

    Fix on a hit: add the kwarg to the offending mapped_column. See
    ``backend/src/models/source.py`` for the canonical pattern.
    """
    offenders = _strenum_columns_without_values_callable()
    assert offenders == [], (
        "The following StrEnum-backed columns are missing values_callable, "
        "which will cause asyncpg/SQLAlchemy enum errors at runtime:\n  - "
        + "\n  - ".join(offenders)
    )


@pytest.mark.parametrize(
    "module_path,column_path",
    [
        ("src.models.source", "Source.source_type"),
        ("src.models.user", "User.role"),
        ("src.models.user", "Invitation.role"),
        ("src.models.sync_job", "SyncJob.status"),
    ],
)
def test_known_strenum_columns_have_lowercase_values_in_pg_type(
    module_path: str, column_path: str
) -> None:
    """Sanity-check that the values bound to PG match the lowercase StrEnum
    values. This is what the Postgres enum types contain in production."""
    import importlib

    module = importlib.import_module(module_path)
    cls_name, attr = column_path.split(".")
    cls = getattr(module, cls_name)
    column = getattr(cls, attr).property.columns[0]
    sa_enum = column.type
    assert isinstance(sa_enum, SAEnum)
    assert sa_enum.values_callable is not None, (
        f"{column_path}: values_callable must be set"
    )
    bound = sa_enum.values_callable(sa_enum.enum_class)
    # Every bound value must be lowercase — that's the contract with the PG
    # enum type. If a future StrEnum legitimately needs uppercase values,
    # the assertion can be relaxed per-column, but flag the change here.
    for value in bound:
        assert value == value.lower(), (
            f"{column_path}: bound value {value!r} is not lowercase"
        )
