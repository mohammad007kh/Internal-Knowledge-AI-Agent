"""Connectors router — CRUD + test-connection for Connector entities.

All endpoints live under ``/api/v1/connectors`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

All endpoints require ``admin`` role.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_role
from src.models.user import User, UserRole
from src.schemas.connector import (
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorUpdate,
)
from src.services.connector_service import ConnectorService

router = APIRouter()

AdminOnly = require_role(UserRole.admin)


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_connector_service(
    db: AsyncSession = Depends(get_db),
) -> ConnectorService:
    """Construct :class:`ConnectorService` bound to the request-scoped DB session.

    The legacy ``Container.connector_service()`` resolver built the repo
    against a *separate* :class:`AsyncSession` the route never committed, so
    create / update / delete (and the ``last_tested_at`` write in
    test-connection) flushed to a doomed session and were silently rolled back
    at GC — same bug class as FX20. Binding the repo to ``Depends(get_db)``
    lets the route's ``await db.commit()`` persist the change.
    """
    from src.core.config import settings  # noqa: PLC0415
    from src.repositories.connector_repository import (  # noqa: PLC0415
        ConnectorRepository,
    )

    return ConnectorService(repo=ConnectorRepository(db), settings=settings)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ConnectorListResponse,
    summary="List connectors",
)
async def list_connectors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
) -> ConnectorListResponse:
    """Return a paginated list of all connectors. Admin-only."""
    skip = (page - 1) * page_size
    items, total = await service.list_connectors(
        owner_id=admin.id, skip=skip, limit=page_size, admin=True
    )
    return ConnectorListResponse(
        items=[ConnectorResponse.model_validate(c) for c in items],
        total=total,
    )


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a connector",
)
async def create_connector(
    payload: ConnectorCreate,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
    db: AsyncSession = Depends(get_db),
) -> ConnectorResponse:
    """Create a new connector owned by the authenticated admin."""
    connector = await service.create_connector(payload, owner_id=admin.id)
    await db.commit()
    return ConnectorResponse.model_validate(connector)


@router.get(
    "/{connector_id}",
    response_model=ConnectorResponse,
    summary="Get a single connector",
)
async def get_connector(
    connector_id: uuid.UUID,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
) -> ConnectorResponse:
    """Return a connector by ID. Admin-only."""
    connector = await service.get_connector(connector_id)
    return ConnectorResponse.model_validate(connector)


@router.patch(
    "/{connector_id}",
    response_model=ConnectorResponse,
    summary="Partially update a connector",
)
async def update_connector(
    connector_id: uuid.UUID,
    payload: ConnectorUpdate,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
    db: AsyncSession = Depends(get_db),
) -> ConnectorResponse:
    """Update name, is_active, or config of a connector. Admin-only."""
    updated = await service.update_connector(connector_id, payload, owner_id=admin.id)
    await db.commit()
    return ConnectorResponse.model_validate(updated)


@router.delete(
    "/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector",
)
async def delete_connector(
    connector_id: uuid.UUID,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete a connector. Admin-only."""
    await service.delete_connector(connector_id, owner_id=admin.id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{connector_id}/test",
    summary="Test connector reachability",
)
async def test_connector(
    connector_id: uuid.UUID,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attempt a live connection using the stored (decrypted) config.

    Always returns ``{"success": bool, "message": str}``.
    """
    result = await service.test_connection(connector_id, owner_id=admin.id)
    # test_connection writes last_tested_at — persist it.
    await db.commit()
    return result
