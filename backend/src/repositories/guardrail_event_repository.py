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

    async def list_events(
        self,
        limit: int = 20,
        offset: int = 0,
        direction: str | None = None,
        blocked: bool | None = None,
    ) -> tuple[list, int]:
        """Return (events, total) for admin listing with optional filters."""
        from sqlalchemy import func, select

        stmt = select(GuardrailEvent).order_by(GuardrailEvent.created_at.desc())
        count_stmt = select(func.count()).select_from(GuardrailEvent)
        if direction:
            stmt = stmt.where(GuardrailEvent.direction == direction)
            count_stmt = count_stmt.where(GuardrailEvent.direction == direction)
        if blocked is not None:
            stmt = stmt.where(GuardrailEvent.blocked == blocked)
            count_stmt = count_stmt.where(GuardrailEvent.blocked == blocked)
        total_res = await self._session.execute(count_stmt)
        total = total_res.scalar() or 0
        res = await self._session.execute(stmt.limit(limit).offset(offset))
        return list(res.scalars().all()), total

    async def get_by_id(self, event_id):
        """Fetch a single guardrail event by id."""
        from sqlalchemy import select

        res = await self._session.execute(
            select(GuardrailEvent).where(GuardrailEvent.id == event_id)
        )
        return res.scalar_one_or_none()
