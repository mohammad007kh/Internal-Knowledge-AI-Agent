"""Integration tests for the source intent API (T-037).

Spec coverage: T-023 (intent API contract)
Endpoints under test:
  GET  /api/v1/sources/{source_id}/intent          → 200 SourceIntent
  PUT  /api/v1/sources/{source_id}/intent          → 200 SourceIntent (status → user_set)
  POST /api/v1/sources/{source_id}/intent/propose  → 202 (async, Celery task)

All three routes are admin-only (require_admin). Non-admin token → 403.
PUT with invalid payload (purpose > 500 chars) → 422.

Guarded by RUN_INTEGRATION_TESTS=1 like the rest of the integration suite.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SourceType
from src.models.source import Source

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _INTEGRATION,
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASS = "Admin@1234"
_USER_EMAIL = "user@example.com"
_USER_PASS = "User@12345"

_INTENT_BASE = "/api/v1/sources"


if _INTEGRATION:
    from tests.conftest import get_access_token

    @pytest_asyncio.fixture
    async def intent_source(
        db_session: AsyncSession,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> Source:
        """Persist a minimal Source owned by admin_user for intent endpoint tests."""
        src = Source(
            id=uuid.uuid4(),
            name="Intent API Test Source",
            source_type=SourceType.WEB_URL,
            owner_id=admin_user.id,  # type: ignore[attr-defined]
            is_active=True,
            config_encrypted=b"placeholder",
        )
        db_session.add(src)
        await db_session.commit()
        await db_session.refresh(src)
        return src

    # -------------------------------------------------------------------------
    # GET /api/v1/sources/{source_id}/intent
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_intent_returns_200(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """GET returns 200 and a body that contains intent_status."""
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent"
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert "intent_status" in body
        # Freshly-created source starts in the pending_ai state (DB default).
        assert body["intent_status"] in {"pending_ai", "ai_set", "user_set"}

    # -------------------------------------------------------------------------
    # PUT /api/v1/sources/{source_id}/intent
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_put_intent_upgrades_to_user_set(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """PUT with valid purpose + example_questions → 200, status becomes user_set."""
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent"
        payload = {
            "purpose": "Answers questions about product onboarding.",
            "example_questions": [
                "How do I create an account?",
                "What is the refund policy?",
            ],
        }
        resp = await client.put(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent_status"] == "user_set"
        assert body["purpose"] == payload["purpose"]

    # -------------------------------------------------------------------------
    # POST /api/v1/sources/{source_id}/intent/propose
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_propose_intent_returns_202(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """POST /propose → 202 Accepted (fire-and-forget; worker is mocked)."""
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent/propose"
        resp = await client.post(url, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 202

    # -------------------------------------------------------------------------
    # Auth / RBAC: non-admin gets 403
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_admin_get_intent_forbidden(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        regular_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """A regular (non-admin) user receives 403 on GET intent."""
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent"
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_admin_put_intent_forbidden(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        regular_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """A regular (non-admin) user receives 403 on PUT intent."""
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent"
        resp = await client.put(
            url,
            json={"purpose": "Should be rejected."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    # -------------------------------------------------------------------------
    # PUT validation: purpose > 500 chars → 422
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_put_intent_422_on_purpose_too_long(
        client: AsyncClient,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
        intent_source: Source,
    ) -> None:
        """PUT with a purpose longer than 500 characters returns 422 Unprocessable."""
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        url = f"{_INTENT_BASE}/{intent_source.id}/intent"
        oversized_purpose = "A" * 501
        resp = await client.put(
            url,
            json={"purpose": oversized_purpose},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
