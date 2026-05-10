"""Admin AI Models CRUD endpoints (`/api/v1/admin/ai-models`).

See §7 of the design doc for the full surface.  All routes use
:func:`require_admin` and write an entry to ``admin_audit_log``.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import decrypt, encrypt, last4
from src.core.database import get_db
from src.core.deps import require_admin
from src.models.ai_model import AIModel
from src.models.llm_configuration import LLMConfiguration
from src.models.user import User
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.ai_model_repository import AIModelRepository
from src.schemas.ai_model import (
    AIModelCreate,
    AIModelList,
    AIModelPublic,
    AIModelUpdate,
    AIModelUsage,
    TestConnectionPlaintextRequest,
    TestConnectionResult,
)
from src.services.audit_service import emit_audit
from src.services.provider_model_metadata import lookup as lookup_metadata

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scrub(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _row_to_public(row: AIModel) -> AIModelPublic:
    plaintext_for_hint: str | None = None
    if row.api_key_encrypted:
        try:
            plaintext_for_hint = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001 - hint only
            plaintext_for_hint = None
    return AIModelPublic(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model_id=row.model_id,
        base_url=row.base_url,
        extra_config=row.extra_config or {},
        default_temperature=row.default_temperature,
        default_max_tokens=row.default_max_tokens,
        capabilities=row.capabilities or {},
        is_active=row.is_active,
        api_key_set=row.api_key_encrypted is not None,
        api_key_last4=last4(plaintext_for_hint),
        last_test_at=row.last_test_at,
        last_test_status=row.last_test_status,
        last_test_error=row.last_test_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )


async def _load_or_404(repo: AIModelRepository, model_id: uuid.UUID) -> AIModel:
    row = await repo.get_by_id(model_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "id": str(model_id)},
        )
    return row


# ---------------------------------------------------------------------------
# Test-connection rate limit helper (per-admin, 10 / 60 s).
# ---------------------------------------------------------------------------


_TEST_RATE_LIMIT = 10
_TEST_RATE_WINDOW = 60


async def _check_test_rate_limit(admin_id: uuid.UUID) -> None:
    """Dedicated 10/60s test-connection limit (security §9.4)."""
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
        count = results[2]
        if count > _TEST_RATE_LIMIT:
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


# ---------------------------------------------------------------------------
# Core OpenAI-compat ping (provider-agnostic best-effort).
# ---------------------------------------------------------------------------


async def _ping_openai_compatible(
    *,
    api_key: str,
    model_id: str,
    base_url: str | None,
) -> tuple[bool, int, str | None]:
    """Send a tiny chat-completion to verify credentials.  Returns (ok, latency_ms, error)."""
    kwargs: dict[str, Any] = {"api_key": api_key or "missing"}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)
    start = time.monotonic()
    try:
        await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return True, int((time.monotonic() - start) * 1000), None
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - start) * 1000)
        return False, latency, _scrub(str(exc), api_key)[:480]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=AIModelList)
async def list_models(
    q: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIModelList:
    repo = AIModelRepository(db)
    rows, total = await repo.search(
        q=q, provider=provider, active=active, limit=limit, offset=offset
    )
    return AIModelList(
        items=[_row_to_public(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=AIModelPublic, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: AIModelCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIModelPublic:
    repo = AIModelRepository(db)
    audit_repo = AdminAuditLogRepository(db)

    # Uniqueness on (provider, base_url, model_id, deployment_name).
    deployment_name = (body.extra_config or {}).get("deployment_name")
    duplicate = await repo.find_duplicate(
        provider=body.provider,
        base_url=body.base_url,
        model_id=body.model_id,
        deployment_name=deployment_name,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate",
                "existing_id": str(duplicate.id),
                "message": "An AI model with this provider/model/base_url already exists.",
            },
        )
    if await repo.get_by_name(body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "name_taken"},
        )

    capabilities = body.capabilities or lookup_metadata(body.provider, body.model_id)
    api_key_encrypted = encrypt(body.api_key) if body.api_key else None

    row = await repo.create(
        name=body.name,
        provider=body.provider,
        model_id=body.model_id,
        base_url=body.base_url,
        api_key_encrypted=api_key_encrypted,
        extra_config=body.extra_config or {},
        default_temperature=body.default_temperature,
        default_max_tokens=body.default_max_tokens,
        capabilities=capabilities,
        is_active=body.is_active,
        created_by=admin.id,
    )
    # Flush (not commit) so row.id is populated and the audit insert can
    # reference it inside the same transaction.
    await db.flush()
    await db.refresh(row)
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="ai_model.create",
        resource_type="ai_model",
        resource_id=row.id,
        request=request,
        metadata={
            "name": row.name,
            "provider": row.provider,
            "model_id": row.model_id,
        },
    )
    await db.commit()
    return _row_to_public(row)


@router.get("/{model_id}", response_model=AIModelPublic)
async def get_model(
    model_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIModelPublic:
    repo = AIModelRepository(db)
    row = await _load_or_404(repo, model_id)
    return _row_to_public(row)


@router.patch("/{model_id}", response_model=AIModelPublic)
async def patch_model(
    model_id: uuid.UUID,
    body: AIModelUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIModelPublic:
    repo = AIModelRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, model_id)

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
    if body.default_temperature is not None:
        fields["default_temperature"] = body.default_temperature
        audit_diff["default_temperature"] = body.default_temperature
    if body.default_max_tokens is not None:
        fields["default_max_tokens"] = body.default_max_tokens
        audit_diff["default_max_tokens"] = body.default_max_tokens
    if body.capabilities is not None:
        fields["capabilities"] = body.capabilities
    if body.is_active is not None:
        fields["is_active"] = body.is_active
        audit_diff["is_active"] = body.is_active

    # api_key tri-state — None means preserve.
    if body.api_key is not None:
        if body.api_key == "":
            fields["api_key_encrypted"] = None
            audit_diff["api_key"] = "cleared"
        else:
            fields["api_key_encrypted"] = encrypt(body.api_key)
            audit_diff["api_key"] = "rotated"

    if fields:
        row = await repo.update_fields(model_id, fields)
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
    await db.commit()
    await db.refresh(row)
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="ai_model.update",
        resource_type="ai_model",
        resource_id=model_id,
        request=request,
        metadata=audit_diff,
    )
    await db.commit()
    return _row_to_public(row)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    repo = AIModelRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, model_id)

    # ON DELETE RESTRICT — surface referencing rows as 409.
    referenced_stages = (
        (
            await db.execute(
                select(LLMConfiguration.slot_name).where(
                    LLMConfiguration.ai_model_id == model_id
                )
            )
        )
        .scalars()
        .all()
    )
    if referenced_stages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "referenced",
                "referenced_by": {"stages": list(referenced_stages)},
            },
        )

    await repo.delete(model_id)
    await db.commit()
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="ai_model.delete",
        resource_type="ai_model",
        resource_id=model_id,
        request=request,
        metadata={"name": row.name, "provider": row.provider},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection_plaintext(
    body: TestConnectionPlaintextRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    """Plaintext-form test — DOES NOT persist the API key."""
    del request  # not used (rate limit is admin-keyed)
    await _check_test_rate_limit(admin.id)
    audit_repo = AdminAuditLogRepository(db)
    ok, latency_ms, err = await _ping_openai_compatible(
        api_key=body.api_key,
        model_id=body.model_id,
        base_url=body.base_url,
    )
    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="ai_model.test",
        resource_type="ai_model",
        resource_id=None,
        request=None,
        metadata={"provider": body.provider, "model_id": body.model_id, "ok": ok},
    )
    await db.commit()
    return TestConnectionResult(ok=ok, latency_ms=latency_ms, error=err)


@router.post("/invalidate-cache", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_resolver_cache(
    _admin: User = Depends(require_admin),
) -> Response:
    """Surgical poke endpoint — clears the AIModelResolver TTL cache.

    NOTE: This static route MUST be registered before the parameterized
    ``POST /{model_id}/test-connection`` route below.  FastAPI matches routes
    in registration order, so swapping these would cause this endpoint to be
    captured by the parameterized route with ``model_id="invalidate-cache"``.
    """
    from src.core.container import container  # noqa: PLC0415

    try:
        resolver = container.ai_model_resolver()
        resolver.invalidate()
    except Exception:  # noqa: BLE001
        logger.warning("invalidate_resolver_cache: resolver not available", exc_info=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{model_id}/test-connection", response_model=TestConnectionResult)
async def test_connection_record(
    model_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    """Record-bound test — updates ``last_test_at`` / ``last_test_status``."""
    del request
    await _check_test_rate_limit(admin.id)
    repo = AIModelRepository(db)
    audit_repo = AdminAuditLogRepository(db)
    row = await _load_or_404(repo, model_id)

    api_key = ""
    if row.api_key_encrypted:
        try:
            api_key = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001
            api_key = ""

    ok, latency_ms, err = await _ping_openai_compatible(
        api_key=api_key,
        model_id=row.model_id,
        base_url=row.base_url,
    )
    await repo.update_fields(
        model_id,
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
        action="ai_model.test",
        resource_type="ai_model",
        resource_id=model_id,
        request=None,
        metadata={"ok": ok, "latency_ms": latency_ms},
    )
    await db.commit()
    return TestConnectionResult(ok=ok, latency_ms=latency_ms, error=err)


@router.get("/{model_id}/usage", response_model=AIModelUsage)
async def get_usage(
    model_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIModelUsage:
    repo = AIModelRepository(db)
    await _load_or_404(repo, model_id)

    stages = (
        (
            await db.execute(
                select(LLMConfiguration.slot_name).where(
                    LLMConfiguration.ai_model_id == model_id
                )
            )
        )
        .scalars()
        .all()
    )

    # TODO(v1.1): chat_messages does not yet snapshot ai_model_id — see
    # design doc §12 risk #3.  Until that column ships, return literal 0
    # rather than running a contradictory query (the previous
    # ``WHERE id IS NULL`` predicate was always 0 by definition and merely
    # masked the missing schema).
    chat_count = 0

    return AIModelUsage(stages=list(stages), chat_messages_count=int(chat_count))
