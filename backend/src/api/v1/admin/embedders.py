"""Admin Embedder CRUD endpoints (`/api/v1/admin/embedders`).

See §7 of the design doc.  ``POST /{id}/activate`` enforces the
v1 invariant that ``dimensions == 1536`` (`DIMENSION_LOCKED_V1`) and
returns 409 with structured error codes per §6.5.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import decrypt, encrypt, last4
from src.core.database import get_db
from src.core.deps import require_admin
from src.models.embedder import Embedder
from src.models.user import User
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.embedder_repository import EmbedderRepository
from src.schemas.embedder import (
    EmbedderActivatePreview,
    EmbedderActivateResponse,
    EmbedderCreate,
    EmbedderList,
    EmbedderPublic,
    EmbedderUpdate,
)
from src.schemas.ai_model import (
    TestConnectionPlaintextRequest,
    TestConnectionResult,
)
from src.services.audit_service import emit_audit

logger = logging.getLogger(__name__)

router = APIRouter()

V1_LOCKED_DIMENSIONS = 1536
_TEST_RATE_LIMIT = 10
_TEST_RATE_WINDOW = 60


# ---------------------------------------------------------------------------
# Helpers (mirror ai_models.py, kept distinct for clarity)
# ---------------------------------------------------------------------------


def _scrub(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _row_to_public(row: Embedder) -> EmbedderPublic:
    plaintext: str | None = None
    if row.api_key_encrypted:
        try:
            plaintext = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001
            plaintext = None
    return EmbedderPublic(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model_id=row.model_id,
        base_url=row.base_url,
        extra_config=row.extra_config or {},
        dimensions=row.dimensions,
        max_input_tokens=row.max_input_tokens,
        is_active=row.is_active,
        api_key_set=row.api_key_encrypted is not None,
        api_key_last4=last4(plaintext),
        last_test_at=row.last_test_at,
        last_test_status=row.last_test_status,
        last_test_error=row.last_test_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )


async def _load_or_404(repo: EmbedderRepository, embedder_id: uuid.UUID) -> Embedder:
    row = await repo.get_by_id(embedder_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "id": str(embedder_id)},
        )
    return row


async def _check_test_rate_limit(admin_id: uuid.UUID) -> None:
    import src.core.redis as redis_module  # noqa: PLC0415

    redis = redis_module.redis_client
    if redis is None:
        return
    key = f"rate:admin-test:{admin_id}"
    now = time.time()
    window_start = now - _TEST_RATE_WINDOW
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, _TEST_RATE_WINDOW)
            results = await pipe.execute()
        if results[2] > _TEST_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limited",
                    "message": (
                        f"Test-connection limit is {_TEST_RATE_LIMIT}/"
                        f"{_TEST_RATE_WINDOW}s per admin user."
                    ),
                },
                headers={"Retry-After": str(_TEST_RATE_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("test-connection rate-limit check failed; allowing request")


async def _ping_embedding_endpoint(
    *,
    api_key: str,
    model_id: str,
    base_url: str | None,
) -> tuple[bool, int, str | None]:
    kwargs: dict[str, Any] = {"api_key": api_key or "missing"}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)
    start = time.monotonic()
    try:
        await client.embeddings.create(model=model_id, input=["ping"])
        return True, int((time.monotonic() - start) * 1000), None
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - start) * 1000)
        return False, latency, _scrub(str(exc), api_key)[:480]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=EmbedderList)
async def list_embedders(
    q: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderList:
    repo = EmbedderRepository(db)
    rows, total = await repo.search(
        q=q, provider=provider, active=active, limit=limit, offset=offset
    )
    return EmbedderList(
        items=[_row_to_public(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=EmbedderPublic, status_code=status.HTTP_201_CREATED)
async def create_embedder(
    body: EmbedderCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderPublic:
    repo = EmbedderRepository(db)
    audit_repo = AdminAuditLogRepository(db)

    duplicate = await repo.find_duplicate(
        provider=body.provider,
        base_url=body.base_url,
        model_id=body.model_id,
        dimensions=body.dimensions,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate",
                "existing_id": str(duplicate.id),
            },
        )
    if await repo.get_by_name(body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "name_taken"},
        )

    api_key_encrypted = encrypt(body.api_key) if body.api_key else None

    # is_active=True at creation requires the v1 dimension lock + partial uniqueness.
    if body.is_active and body.dimensions != V1_LOCKED_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "DIMENSION_LOCKED_V1", "expected": V1_LOCKED_DIMENSIONS},
        )

    row = await repo.create(
        name=body.name,
        provider=body.provider,
        model_id=body.model_id,
        base_url=body.base_url,
        api_key_encrypted=api_key_encrypted,
        extra_config=body.extra_config or {},
        dimensions=body.dimensions,
        max_input_tokens=body.max_input_tokens,
        is_active=body.is_active,
        created_by=admin.id,
    )
    # Flush so the row gets its server-side defaults (id, created_at) and
    # downstream emit_audit() can reference row.id without committing yet.
    await db.flush()
    await db.refresh(row)
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="embedder.create",
        resource_type="embedder",
        resource_id=row.id,
        request=request,
        metadata={
            "name": row.name,
            "provider": row.provider,
            "model_id": row.model_id,
            "dimensions": row.dimensions,
        },
    )
    await db.commit()
    return _row_to_public(row)


@router.get("/{embedder_id}", response_model=EmbedderPublic)
async def get_embedder(
    embedder_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderPublic:
    repo = EmbedderRepository(db)
    return _row_to_public(await _load_or_404(repo, embedder_id))


@router.patch("/{embedder_id}", response_model=EmbedderPublic)
async def patch_embedder(
    embedder_id: uuid.UUID,
    body: EmbedderUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderPublic:
    repo = EmbedderRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, embedder_id)

    fields: dict[str, Any] = {}
    audit_diff: dict[str, Any] = {}
    if body.name is not None and body.name != row.name:
        if await repo.get_by_name(body.name) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "name_taken"},
            )
        fields["name"] = body.name
        audit_diff["name"] = body.name
    if body.provider is not None:
        fields["provider"] = body.provider
        audit_diff["provider"] = body.provider
    if body.model_id is not None:
        fields["model_id"] = body.model_id
        audit_diff["model_id"] = body.model_id
    if body.base_url is not None:
        fields["base_url"] = body.base_url
        audit_diff["base_url"] = body.base_url
    if body.extra_config is not None:
        fields["extra_config"] = body.extra_config
    if body.max_input_tokens is not None:
        fields["max_input_tokens"] = body.max_input_tokens
    if body.is_active is not None:
        # PATCH is_active flips through the partial-unique index; for v1 we
        # require the dedicated /activate endpoint when turning ON.
        if body.is_active and not row.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "USE_ACTIVATE_ENDPOINT",
                    "message": "Use POST /{id}/activate to activate (re-embed required).",
                },
            )
        fields["is_active"] = body.is_active
        audit_diff["is_active"] = body.is_active
    if body.api_key is not None:
        if body.api_key == "":
            fields["api_key_encrypted"] = None
            audit_diff["api_key"] = "cleared"
        else:
            fields["api_key_encrypted"] = encrypt(body.api_key)
            audit_diff["api_key"] = "rotated"

    if fields:
        row = await repo.update_fields(embedder_id, fields)
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
    await db.commit()
    await db.refresh(row)
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="embedder.update",
        resource_type="embedder",
        resource_id=embedder_id,
        request=request,
        metadata=audit_diff,
    )
    await db.commit()
    return _row_to_public(row)


@router.delete("/{embedder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_embedder(
    embedder_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    repo = EmbedderRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, embedder_id)

    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "BLOCKED_ACTIVE"},
        )
    sources_count = await repo.count_sources_using(embedder_id)
    chunks_count = await repo.count_chunks_using(embedder_id)
    if sources_count or chunks_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "BLOCKED_REFERENCED",
                "referenced_by": {
                    "sources": sources_count,
                    "chunks": chunks_count,
                },
            },
        )
    await repo.delete(embedder_id)
    await db.commit()
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="embedder.delete",
        resource_type="embedder",
        resource_id=embedder_id,
        request=request,
        metadata={"name": row.name},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection_plaintext(
    body: TestConnectionPlaintextRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    await _check_test_rate_limit(admin.id)
    audit_repo = AdminAuditLogRepository(db)
    ok, latency_ms, err = await _ping_embedding_endpoint(
        api_key=body.api_key,
        model_id=body.model_id,
        base_url=body.base_url,
    )
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="embedder.test",
        resource_type="embedder",
        resource_id=None,
        request=None,
        metadata={"provider": body.provider, "model_id": body.model_id, "ok": ok},
    )
    await db.commit()
    return TestConnectionResult(ok=ok, latency_ms=latency_ms, error=err)


@router.post("/{embedder_id}/test-connection", response_model=TestConnectionResult)
async def test_connection_record(
    embedder_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    await _check_test_rate_limit(admin.id)
    repo = EmbedderRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, embedder_id)

    api_key = ""
    if row.api_key_encrypted:
        try:
            api_key = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001
            api_key = ""
    ok, latency_ms, err = await _ping_embedding_endpoint(
        api_key=api_key,
        model_id=row.model_id,
        base_url=row.base_url,
    )
    await repo.update_fields(
        embedder_id,
        {
            "last_test_at": datetime.now(UTC),
            "last_test_status": "ok" if ok else "failed",
            "last_test_error": err,
        },
    )
    await db.commit()
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="embedder.test",
        resource_type="embedder",
        resource_id=embedder_id,
        request=None,
        metadata={"ok": ok, "latency_ms": latency_ms},
    )
    await db.commit()
    return TestConnectionResult(ok=ok, latency_ms=latency_ms, error=err)


@router.get("/{embedder_id}/activate-preview", response_model=EmbedderActivatePreview)
async def activate_preview(
    embedder_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderActivatePreview:
    """Cheap dry-run — counts chunks that would be re-embedded."""
    repo = EmbedderRepository(db)
    await _load_or_404(repo, embedder_id)

    from sqlalchemy import func, select  # noqa: PLC0415
    from src.models.chunk import Chunk  # noqa: PLC0415

    chunk_count = (
        await db.execute(select(func.count()).select_from(Chunk))
    ).scalar_one()
    chunk_count = int(chunk_count or 0)
    # Conservative pricing — see §6.5 (estimates only).
    estimated_seconds = max(60, chunk_count // 1000 * 6)
    estimated_cost = round(chunk_count * 0.00002, 4)
    return EmbedderActivatePreview(
        chunks_to_reembed=chunk_count,
        estimated_seconds=estimated_seconds,
        estimated_api_cost_usd=estimated_cost,
    )


@router.post("/{embedder_id}/activate", response_model=EmbedderActivateResponse)
async def activate_embedder(
    embedder_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmbedderActivateResponse:
    """Kick off a Celery re-embed job and atomically swap the active embedder.

    Returns 409 with structured error codes per §6.5:
    ``DIMENSION_LOCKED_V1`` / ``UNTESTED_EMBEDDER`` / ``ACTIVATION_IN_PROGRESS``.
    """
    repo = EmbedderRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, embedder_id)

    if row.dimensions != V1_LOCKED_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "DIMENSION_LOCKED_V1",
                "actual": row.dimensions,
                "expected": V1_LOCKED_DIMENSIONS,
            },
        )
    fresh_threshold = datetime.now(UTC) - timedelta(hours=24)
    if (
        row.last_test_status != "ok"
        or row.last_test_at is None
        or row.last_test_at < fresh_threshold
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "UNTESTED_EMBEDDER",
                "message": "Run /test-connection within the last 24h before activating.",
            },
        )

    # Synchronous activation for v1 — re-embed batch job is deferred to v1.1.
    # We simply flip `is_active` (the partial unique index will reject if
    # another row is active).  The audit row is emitted in the SAME
    # transaction as the activation flip so a row that "happened" in the DB
    # is always accompanied by its audit trail (and vice versa).
    if not row.is_active:
        # Deactivate any current active row, then mark this one active.
        prior = await repo.get_active()
        if prior is not None:
            await repo.update_fields(prior.id, {"is_active": False})
        await repo.update_fields(embedder_id, {"is_active": True})
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="activate",
        resource_type="embedder",
        resource_id=embedder_id,
        request=request,
        metadata={"target_embedder_id": str(embedder_id)},
    )
    await db.commit()

    # Reset factory cache so subsequent retrievals see the new active row.
    try:
        from src.core.container import container  # noqa: PLC0415

        factory = container.embedding_service_factory()
        factory.invalidate()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to invalidate embedding factory cache", exc_info=True)

    return EmbedderActivateResponse(job_id=str(uuid.uuid4()), status="active")
