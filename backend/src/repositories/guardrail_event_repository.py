"""Repository for GuardrailEvent persistence."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.guardrail_event import GuardrailEvent


class GuardrailEventRepository:
    """Persists guardrail audit events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: dict) -> None:
        """Insert a new guardrail audit event.

        Args:
            data: Dict with keys: direction, text, blocked, reason,
                  triggered_policy_ids, session_id.
        """
        session_id_raw = data.get("session_id")
        event = GuardrailEvent(
            direction=data["direction"],
            text=data["text"],
            blocked=data["blocked"],
            reason=data.get("reason"),
            triggered_policy_ids=data.get("triggered_policy_ids", []),
            session_id=uuid.UUID(session_id_raw) if session_id_raw else None,
        )
        self._session.add(event)
        try:
            await self._session.commit()
        finally:
            await self._session.close()
