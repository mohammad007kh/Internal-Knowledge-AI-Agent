"""ORM model stub for CompanyPolicy (FR-GUARDRAIL-*)."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class CompanyPolicy(Base, UUIDMixin, TimestampMixin):
    """Company-defined policy rule evaluated by the guardrail layer.

    Attributes:
        rule_text: Natural-language policy rule text.
        is_active: When ``False`` the rule is ignored during evaluation.
        created_by: UUID of the admin who created the rule.
    """

    __tablename__ = "company_policies"

    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
