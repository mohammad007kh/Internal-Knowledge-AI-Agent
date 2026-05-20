"""Integration tests for GET /api/v1/sources — T-107 ingestion clarity.

Asserts that the list endpoint returns the eight ingestion-clarity fields
on every row (status, last_synced_at, description, source_mode, sync_mode,
document_count, chunk_count, has_upload) — and that the counts reflect
real Document/Chunk rows seeded against the source.

Guarded by RUN_INTEGRATION_TESTS=1 like the rest of the integration suite
because it needs a live PostgreSQL.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk import Chunk
from src.models.document import Document
from src.models.enums import SourceType
from src.models.source import Source

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _INTEGRATION,
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


_CLARITY_FIELDS = {
    "status",
    "last_synced_at",
    "description",
    "source_mode",
    "sync_mode",
    "document_count",
    "chunk_count",
    "has_upload",
}


if _INTEGRATION:

    @pytest_asyncio.fixture
    async def seeded_source_with_counts(
        db_session: AsyncSession,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> Source:
        """Persist a Source plus 2 Documents and 5 Chunks so the counts are real."""
        src = Source(
            id=uuid.uuid4(),
            name="Clarity Source",
            source_type=SourceType.FILE_UPLOAD,
            owner_id=admin_user.id,  # type: ignore[attr-defined]
            is_active=True,
            config_encrypted=b"placeholder",
            file_storage_path="uploads/2026/05/abc-foo.pdf",
            description="seeded for clarity",
            status="ready",
            source_mode="snapshot",
            sync_mode="manual",
        )
        db_session.add(src)
        await db_session.flush()

        # 2 active documents
        for i in range(2):
            db_session.add(
                Document(
                    id=uuid.uuid4(),
                    source_id=src.id,
                    raw_text=f"doc {i}",
                    is_active=True,
                )
            )
        await db_session.flush()

        # 5 chunks (Chunk.embedding is NOT NULL — embedded == chunked)
        embedding = [0.0] * 1536
        for i in range(5):
            db_session.add(
                Chunk(
                    id=uuid.uuid4(),
                    source_id=src.id,
                    chunk_text=f"chunk {i}",
                    chunk_index=i,
                    embedding=embedding,
                )
            )
        await db_session.commit()
        await db_session.refresh(src)
        return src

    @pytest.mark.asyncio
    async def test_list_returns_clarity_fields(
        client: AsyncClient,
        admin_token: str,
        seeded_source_with_counts: Source,  # noqa: ARG001
    ) -> None:
        """GET /api/v1/sources returns the eight ingestion-clarity keys."""
        response = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert items, "expected at least one source in the listing"
        for item in items:
            missing = _CLARITY_FIELDS - set(item.keys())
            assert not missing, f"missing clarity fields: {missing}"

    @pytest.mark.asyncio
    async def test_list_counts_match_seeded_rows(
        client: AsyncClient,
        admin_token: str,
        seeded_source_with_counts: Source,
    ) -> None:
        """document_count / chunk_count reflect the seeded rows; has_upload=True."""
        response = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        target = next(
            (i for i in items if i["id"] == str(seeded_source_with_counts.id)),
            None,
        )
        assert target is not None, "seeded source missing from list"
        assert target["document_count"] == 2
        assert target["chunk_count"] == 5
        assert target["has_upload"] is True
        # The path itself must NEVER leak — only the boolean.
        assert "file_storage_path" not in target

    @pytest.mark.asyncio
    async def test_list_zero_counts_for_empty_source(
        client: AsyncClient,
        admin_token: str,
        db_session: AsyncSession,
        admin_user,  # type: ignore[no-untyped-def]  # noqa: ARG001
    ) -> None:
        """A source with no documents/chunks reports zero, not null."""
        empty = Source(
            id=uuid.uuid4(),
            name="Empty Source",
            source_type=SourceType.WEB_URL,
            owner_id=admin_user.id,  # type: ignore[attr-defined]
            is_active=False,
            config_encrypted=b"x",
        )
        db_session.add(empty)
        await db_session.commit()

        response = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        target = next((i for i in items if i["id"] == str(empty.id)), None)
        assert target is not None
        assert target["document_count"] == 0
        assert target["chunk_count"] == 0
        assert target["has_upload"] is False
