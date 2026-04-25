"""Static provider catalog endpoint (`/api/v1/admin/providers`).

Exposes the LLM + embedder catalogs that the frontend hydrates into its
provider/model dropdowns.  See ``src/services/provider_catalog.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.core.deps import require_admin
from src.models.user import User
from src.services.provider_catalog import build_catalog_payload

router = APIRouter()


@router.get("/")
async def get_provider_catalog(
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return the full LLM + embedder provider catalog."""
    return build_catalog_payload()
