"""Admin LLM settings routes (T-009 — rewired for AI_MODELS_V2).

Per §7 of the design doc:

* ``GET /`` returns 13 stage configs, each enriched with the linked
  ``ai_model: {id, name, provider, model_id, capabilities}`` plus the
  per-stage overrides ``{temperature, max_tokens, custom_prompt}``.
* ``PUT /{stage}`` accepts ``{ai_model_id, temperature?, max_tokens?,
  custom_prompt?}`` — no more inline provider/model/api_key.
* ``POST /{stage}/test`` resolves the linked AI Model and pings it.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import decrypt
from src.core.database import get_db
from src.core.deps import require_admin
from src.models.ai_model import AIModel
from src.models.llm_configuration import LLMConfiguration
from src.models.user import User
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.ai_model_repository import AIModelRepository
from src.repositories.llm_config_repository import LLMConfigRepository
from src.services.audit_service import emit_audit

logger = logging.getLogger(__name__)

router = APIRouter()


STAGES: list[str] = [
    "schema_inspector",
    "clarification_detector",
    "query_analyzer",
    "source_router",
    "retrieval",
    "text_to_query",
    "synthesizer",
    "reflector",
    "input_guard",
    "output_guard",
    "titler",
    "planner",
    "retrieval_grader",
]

STAGE_META: dict[str, tuple[str, str]] = {
    "schema_inspector": (
        "Schema Inspector",
        "Inspects source schema and generates descriptions",
    ),
    "clarification_detector": (
        "Clarification Detector",
        "Detects if a user query needs clarification",
    ),
    "query_analyzer": ("Query Analyzer", "Analyses and rewrites user queries"),
    "source_router": ("Source Router", "Routes queries to the correct source(s)"),
    "retrieval": ("Retrieval", "Retrieves relevant chunks from the vector store"),
    "text_to_query": ("Text to Query", "Converts natural language to structured queries"),
    "synthesizer": ("Synthesizer", "Synthesises the final answer from context"),
    "reflector": ("Reflector", "Reflects on and improves answers"),
    "input_guard": ("Input Guard", "Policy/safety guard on user input"),
    "output_guard": ("Output Guard", "Policy/safety guard on model output"),
    "titler": (
        "Auto Titler",
        "Generates short sidebar-style titles for new chat sessions",
    ),
    "planner": (
        "Planner",
        "Decomposes a question into dependent, executable steps",
    ),
    "retrieval_grader": (
        "Retrieval Grader",
        "Grades retrieved context for light + heavy verification",
    ),
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AIModelLinkPublic(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    model_id: str
    capabilities: dict[str, Any]


class LLMStageConfigPublic(BaseModel):
    stage: str
    label: str
    description: str
    ai_model: AIModelLinkPublic | None
    temperature: float | None
    max_tokens: int | None
    custom_prompt: str | None
    enabled: bool


class UpdateStageRequest(BaseModel):
    ai_model_id: uuid.UUID
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    custom_prompt: str | None = None


class TestConnectionResult(BaseModel):
    success: bool
    latency_ms: int
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scrub(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _row_to_public(
    stage: str,
    row: LLMConfiguration | None,
    ai_model: AIModel | None,
) -> LLMStageConfigPublic:
    label, description = STAGE_META[stage]
    ai_model_link: AIModelLinkPublic | None = None
    if ai_model is not None:
        ai_model_link = AIModelLinkPublic(
            id=ai_model.id,
            name=ai_model.name,
            provider=ai_model.provider,
            model_id=ai_model.model_id,
            capabilities=ai_model.capabilities or {},
        )
    return LLMStageConfigPublic(
        stage=stage,
        label=label,
        description=description,
        ai_model=ai_model_link,
        temperature=row.temperature if row is not None else None,
        max_tokens=row.max_tokens if row is not None else None,
        custom_prompt=row.custom_prompt if row is not None else None,
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[LLMStageConfigPublic])
async def list_stage_configs(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[LLMStageConfigPublic]:
    """Return all 13 stages enriched with their linked AI model record."""
    repo = LLMConfigRepository(db)
    ai_repo = AIModelRepository(db)
    rows = await repo.get_all()
    by_slot = {r.slot_name: r for r in rows}

    # Pre-load all referenced AI models in one go.
    ai_ids = {r.ai_model_id for r in rows if r.ai_model_id is not None}
    ai_models: dict[uuid.UUID, AIModel] = {}
    for ai_id in ai_ids:
        ai = await ai_repo.get_by_id(ai_id)
        if ai is not None:
            ai_models[ai.id] = ai

    out: list[LLMStageConfigPublic] = []
    for stage in STAGES:
        row = by_slot.get(stage)
        ai = ai_models.get(row.ai_model_id) if row and row.ai_model_id else None
        out.append(_row_to_public(stage, row, ai))
    return out


@router.put("/{stage}", response_model=LLMStageConfigPublic)
async def update_stage_config(
    stage: str,
    body: UpdateStageRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMStageConfigPublic:
    """Link *stage* to an existing AI Model record, with optional overrides."""
    if stage not in STAGE_META:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"title": "Unknown stage", "detail": f"Unknown stage: {stage}"},
        )

    repo = LLMConfigRepository(db)
    ai_repo = AIModelRepository(db)
    audit_repo = AdminAuditLogRepository(db)

    ai_model = await ai_repo.get_by_id(body.ai_model_id)
    if ai_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "ai_model_not_found", "id": str(body.ai_model_id)},
        )

    # Defaults inherited from the AI model when overrides are absent.
    temperature = (
        body.temperature if body.temperature is not None else ai_model.default_temperature
    )
    max_tokens = (
        body.max_tokens if body.max_tokens is not None else ai_model.default_max_tokens
    )

    data: dict[str, Any] = {
        "ai_model_id": ai_model.id,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "custom_prompt": body.custom_prompt,
        # Legacy columns are kept in sync for the migration window.
        "provider": ai_model.provider,
        "model_name": ai_model.model_id,
    }
    row = await repo.upsert(stage, data)

    # Invalidate resolver cache for this stage so the change takes effect now.
    try:
        from src.core.container import container  # noqa: PLC0415

        container.ai_model_resolver().invalidate(stage)
    except Exception:  # noqa: BLE001
        logger.warning("ai_model_resolver invalidation failed", exc_info=True)

    await emit_audit(
        audit_repo,
        admin_user_id=admin.id,
        action="llm_setting.update",
        resource_type="llm_setting",
        resource_id=row.id,
        request=request,
        metadata={
            "stage": stage,
            "ai_model_id": str(ai_model.id),
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    await db.commit()
    return _row_to_public(stage, row, ai_model)


@router.post("/{stage}/test", response_model=TestConnectionResult)
async def test_stage_connection(
    stage: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    """Resolve the AI Model linked to *stage* and ping it."""
    if stage not in STAGE_META:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"title": "Unknown stage", "detail": f"Unknown stage: {stage}"},
        )
    del admin

    repo = LLMConfigRepository(db)
    ai_repo = AIModelRepository(db)
    row = await repo.get_by_slot(stage)
    if row is None or row.ai_model_id is None:
        return TestConnectionResult(
            success=False,
            latency_ms=0,
            message="No AI model linked to this stage",
        )
    ai_model = await ai_repo.get_by_id(row.ai_model_id)
    if ai_model is None or not ai_model.api_key_encrypted:
        return TestConnectionResult(
            success=False,
            latency_ms=0,
            message="Linked AI model is missing or has no API key",
        )

    try:
        api_key = decrypt(ai_model.api_key_encrypted)
    except Exception:  # noqa: BLE001
        return TestConnectionResult(
            success=False,
            latency_ms=0,
            message="Stored API key is unreadable (re-enter under /admin/ai-models).",
        )

    kwargs: dict[str, str] = {"api_key": api_key}
    if ai_model.base_url:
        kwargs["base_url"] = ai_model.base_url
    client = AsyncOpenAI(**kwargs)
    start = time.monotonic()
    try:
        await client.chat.completions.create(
            model=ai_model.model_id,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - start) * 1000)
        return TestConnectionResult(
            success=False,
            latency_ms=latency_ms,
            message=_scrub(str(exc), api_key)[:480],
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    return TestConnectionResult(success=True, latency_ms=latency_ms, message="ok")
