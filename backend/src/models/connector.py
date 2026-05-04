"""Connector ORM model.

Represents a reusable connector configuration that can be used to test
and manage connections to external data sources.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.enums import SourceType


class Connector(Base, UUIDMixin, TimestampMixin):
    """A reusable connector owned by a user."""

    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    connector_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            name="sourcetype",
            create_constraint=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_tested_at: Mapped[None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Connector id={self.id} name={self.name!r} type={self.connector_type}>"
