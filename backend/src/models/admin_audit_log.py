"""AdminAuditLog ORM model — append-only audit trail for admin CRUD actions.

Records every create / update / delete / activate / test on the admin-managed
``ai_models``, ``embedders``, and ``llm_configurations`` tables.

The ``metadata`` JSONB blob captures action params (with API keys redacted).
``api_key`` MUST never appear in metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class AdminAuditLog(Base):
    """Append-only audit-log row for admin actions on AI / Embedder tables."""

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, index=True
    )
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(  # type: ignore[type-arg]
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------ #
    # Logging hygiene — never round-trip the metadata blob into __repr__  #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Dict representation; ``metadata`` already excludes API keys by contract."""
        return {
            c.name: getattr(self, c.name) if c.name != "metadata" else self.metadata_
            for c in self.__table__.columns
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AdminAuditLog id={self.id} action={self.action!r}"
            f" resource_type={self.resource_type!r}"
            f" resource_id={self.resource_id}>"
        )
