"""Connectors router — CRUD + test-connection for Connector entities.

All endpoints live under ``/api/v1/connectors`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

All endpoints require ``admin`` role.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

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


def _get_connector_service() -> ConnectorService:
    """Resolve :class:`ConnectorService` from the DI container."""
    from src.core.container import Container  # noqa: PLC0415

    return Container.connector_service()


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
) -> ConnectorResponse:
    """Create a new connector owned by the authenticated admin."""
    connector = await service.create_connector(payload, owner_id=admin.id)
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


@router.put(
    "/{connector_id}",
    response_model=ConnectorResponse,
    summary="Update a connector",
)
async def update_connector(
    connector_id: uuid.UUID,
    payload: ConnectorUpdate,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
) -> ConnectorResponse:
    """Update name, is_active, or config of a connector. Admin-only."""
    updated = await service.update_connector(connector_id, payload, owner_id=admin.id)
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
) -> Response:
    """Hard-delete a connector. Admin-only."""
    await service.delete_connector(connector_id, owner_id=admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{connector_id}/test",
    summary="Test connector reachability",
)
async def test_connector(
    connector_id: uuid.UUID,
    admin: User = Depends(AdminOnly),
    service: ConnectorService = Depends(_get_connector_service),
) -> dict:
    """Attempt a live connection using the stored (decrypted) config.

    Always returns ``{"success": bool, "message": str}``.
    """
    return await service.test_connection(connector_id, owner_id=admin.id)
