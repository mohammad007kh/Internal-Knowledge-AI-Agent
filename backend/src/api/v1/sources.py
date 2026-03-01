"""Sources router – CRUD + test-connection for Source entities (T-044).

All endpoints live under ``/api/v1/sources`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).

Admin users see all active sources; regular users see only their own.
The ``config`` / ``config_encrypted`` field is never returned in any response.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from src.core.deps import get_current_user
from src.models.user import User, UserRole
from src.schemas.source import (
    PaginatedSources,
    SourceCreate,
    SourceListItem,
    SourceResponse,
    SourceUpdate,
    TestConnectionResponse,
)
from src.schemas.sync_job import SyncJobResponse
from src.services.source_service import SourceService

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def _get_source_service() -> SourceService:
    """Resolve :class:`SourceService` from the DI container.

    Uses a lazy import so that the module can be loaded without triggering
    the full container wiring (helpful for unit tests).
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.source_service()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _assert_ownership_or_admin(owner_id: uuid.UUID, user: User) -> None:
    """Raise 403 if *user* is neither the owner nor an admin."""
    if user.role != UserRole.admin and user.id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "https://httpstatuses.com/403",
                "title": "Forbidden",
                "status": 403,
                "detail": "You are not authorised to access this source.",
            },
        )


def _make_list_item(source: object) -> SourceListItem:
    """Build a slim SourceListItem, attaching the latest sync job when available."""
    latest_raw = max(
        getattr(source, "sync_jobs", []),
        key=lambda j: j.created_at,
        default=None,
    )
    item = SourceListItem.model_validate(source)
    if latest_raw is not None:
        item.latest_job = SyncJobResponse.model_validate(latest_raw)
    return item


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new source",
)
async def create_source(
    payload: SourceCreate,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> SourceResponse:
    """Create a source owned by the authenticated user.

    Connection config is Fernet-encrypted before persistence.
    """
    source = await service.create_source(payload, owner_id=current_user.id)
    return SourceResponse.model_validate(source)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedSources,
    summary="List sources",
)
async def list_sources(
    offset: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> PaginatedSources:
    """Return a paginated list of sources.

    Admins receive all active sources; regular users receive only their own
    sources (both active and inactive).
    """
    if current_user.role == UserRole.admin:
        items, total = await service.list_all_active_sources(skip=offset, limit=limit)
    else:
        items, total = await service.list_sources_for_owner(
            owner_id=current_user.id, skip=offset, limit=limit
        )
    return PaginatedSources(
        items=[_make_list_item(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get a single source",
)
async def get_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> SourceResponse:
    """Return the source if the caller is its owner or an admin.

    Raises 404 if the source does not exist, 403 if unauthorised.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    return SourceResponse.model_validate(source)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Partially update a source",
)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> SourceResponse:
    """Update only the provided fields.

    If ``config`` is included it is re-encrypted before persistence.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    updated = await service.update_source(source_id, payload)
    return SourceResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a source",
)
async def delete_source(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> Response:
    """Set ``is_active = False``.

    The source record is retained for audit purposes.
    Raises 404 if the source does not exist.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    await service.delete_source(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@router.post(
    "/{source_id}/test-connection",
    response_model=TestConnectionResponse,
    summary="Test connector reachability",
)
async def test_connection(
    source_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SourceService = Depends(_get_source_service),
) -> TestConnectionResponse:
    """Attempt a live connection using the stored (decrypted) config.

    Always returns ``{"success": bool}`` — never raises 5xx for connectivity
    failures.
    """
    source = await service.get_source(source_id)
    _assert_ownership_or_admin(source.owner_id, current_user)
    ok = await service.test_connection(source_id)
    return TestConnectionResponse(
        success=ok,
        message="" if ok else "Connection attempt failed — check credentials and network.",
    )
