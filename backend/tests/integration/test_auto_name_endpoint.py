"""Integration tests for POST /api/v1/sources/{id}/auto-name (F7).

Verifies the new endpoint plus the deprecated ``/refresh-description``
alias share the same proposal pipeline (profile → naming) but expose
different response shapes. Auth gating (401 / 403) and 404-on-unknown
are also covered here.

Mocks the SourceProfilerFactory and SourceNamingService at the DI
container level so the route exercises the real auth / DB / routing
stack without needing an actual LLM.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import SourceType
from src.models.source import Source
from src.services.source_naming_service import AINaming
from src.services.source_profiling.protocol import SourceProfile

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _INTEGRATION,
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


if _INTEGRATION:

    # ------------------------------------------------------------------ #
    # Builders                                                            #
    # ------------------------------------------------------------------ #

    def _fake_profile(source: Source) -> SourceProfile:
        return SourceProfile(
            source_id=str(source.id),
            source_type=source.source_type,
            topics=["sales reports"],
            entities=["Acme"],
            content_types=["PDF"],
            coverage_summary="Quarterly sales reports.",
            scope_exclusions="No HR data.",
            sample_count=3,
        )

    def _fake_naming() -> AINaming:
        return AINaming(
            name="Q4 Sales Reports",
            description=(
                "Quarterly sales reporting bundle. Covers: sales reports, "
                "Q4 numbers. Useful for questions about Q4 revenue, account "
                "owners. Does not contain HR records."
            ),
        )

    @pytest_asyncio.fixture
    async def admin_owned_source(
        db_session: AsyncSession,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> Source:
        """Persist a Source owned by the admin user."""
        src = Source(
            id=uuid.uuid4(),
            name="Naming Source",
            source_type=SourceType.FILE_UPLOAD,
            owner_id=admin_user.id,  # type: ignore[attr-defined]
            is_active=True,
            config_encrypted=b"placeholder",
        )
        db_session.add(src)
        await db_session.commit()
        await db_session.refresh(src)
        return src

    @pytest.fixture
    def mocked_proposal_stack():
        """Patch the DI container's profiler factory + naming service so
        the route logic runs without an LLM call.

        Yields the (factory, naming_service) mocks so tests can assert
        they were called correctly.
        """
        factory = MagicMock()
        profiler = MagicMock()
        profiler.profile = AsyncMock()
        factory.for_source.return_value = profiler

        naming_service = MagicMock()
        naming_service.name_from_profile = AsyncMock(return_value=_fake_naming())

        with (
            patch(
                "src.core.container.Container.source_profiler_factory",
                return_value=factory,
            ),
            patch(
                "src.core.container.Container.source_naming_service",
                return_value=naming_service,
            ),
        ):
            yield factory, profiler, naming_service

    # ------------------------------------------------------------------ #
    # Happy path                                                          #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_auto_name_returns_proposed_name_and_description(
        client: AsyncClient,
        admin_token: str,
        admin_owned_source: Source,
        mocked_proposal_stack,  # noqa: ARG001
    ) -> None:
        factory, profiler, naming_service = mocked_proposal_stack
        profiler.profile.return_value = _fake_profile(admin_owned_source)

        resp = await client.post(
            f"/api/v1/sources/{admin_owned_source.id}/auto-name",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["proposed_name"] == "Q4 Sales Reports"
        assert "Quarterly sales reporting bundle." in body["proposed_description"]
        # Persistence is intentionally a separate flow.
        factory.for_source.assert_called_once()
        naming_service.name_from_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deprecated_refresh_description_returns_only_description(
        client: AsyncClient,
        admin_token: str,
        admin_owned_source: Source,
        mocked_proposal_stack,
    ) -> None:
        _factory, profiler, _naming_service = mocked_proposal_stack
        profiler.profile.return_value = _fake_profile(admin_owned_source)

        resp = await client.post(
            f"/api/v1/sources/{admin_owned_source.id}/refresh-description",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        # Deprecated alias: only the description is exposed (back-compat).
        assert "proposed_description" in body
        assert "proposed_name" not in body

    # ------------------------------------------------------------------ #
    # Auth                                                                #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_auto_name_unauthenticated_returns_401(
        client: AsyncClient,
        admin_owned_source: Source,
    ) -> None:
        resp = await client.post(
            f"/api/v1/sources/{admin_owned_source.id}/auto-name",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_auto_name_non_admin_returns_403(
        client: AsyncClient,
        user_token: str,
        admin_owned_source: Source,
    ) -> None:
        resp = await client.post(
            f"/api/v1/sources/{admin_owned_source.id}/auto-name",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    # ------------------------------------------------------------------ #
    # 404                                                                  #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_auto_name_unknown_source_returns_404(
        client: AsyncClient,
        admin_token: str,
        mocked_proposal_stack,  # noqa: ARG001
    ) -> None:
        ghost = uuid.uuid4()
        resp = await client.post(
            f"/api/v1/sources/{ghost}/auto-name",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
