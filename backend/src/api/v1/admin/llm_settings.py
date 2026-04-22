"""Admin LLM settings routes (T-009)."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.core.deps import require_admin
from src.models.user import User

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
    "query_analyzer": (
        "Query Analyzer",
        "Analyses and rewrites user queries",
    ),
    "source_router": (
        "Source Router",
        "Routes queries to the correct source(s)",
    ),
    "retrieval": (
        "Retrieval",
        "Retrieves relevant chunks from the vector store",
    ),
    "text_to_query": (
        "Text to Query",
        "Converts natural language to structured queries",
    ),
    "synthesizer": (
        "Synthesizer",
        "Synthesises the final answer from context",
    ),
    "reflector": (
        "Reflector",
        "Reflects on and improves answers",
    ),
    "input_guard": (
        "Input Guard",
        "Policy/safety guard on user input",
    ),
    "output_guard": (
        "Output Guard",
        "Policy/safety guard on model output",
    ),
}


DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048


class UpdateLLMConfigRequest(BaseModel):
    provider: str
    model: str
    api_key: str | None = None  # None = keep existing
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    enabled: bool = True


class LLMStageConfigPublic(BaseModel):
    stage: str
    label: str
    description: str
    provider: str
    model: str
    api_key_hint: str | None  # last 4 chars only
    temperature: float
    max_tokens: int
    enabled: bool


class TestConnectionResult(BaseModel):
    success: bool
    latency_ms: int
    message: str


def _hint_from_encrypted(blob: bytes | None) -> str | None:
    if not blob:
        return None
    try:
        s = blob.decode("utf-8", errors="replace")
    except Exception:
        return "****"
    return s[-4:] if len(s) >= 4 else s


def _row_to_public(stage: str, row: Any | None) -> LLMStageConfigPublic:
    label, description = STAGE_META[stage]
    if row is None:
        return LLMStageConfigPublic(
            stage=stage,
            label=label,
            description=description,
            provider=DEFAULT_PROVIDER,
            model=DEFAULT_MODEL,
            api_key_hint=None,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            enabled=True,
        )
    return LLMStageConfigPublic(
        stage=stage,
        label=label,
        description=description,
        provider=row.provider,
        model=row.model_name,
        api_key_hint=_hint_from_encrypted(row.api_key_encrypted),
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        enabled=True,
    )


def _scrub(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


@router.get("/", response_model=list[LLMStageConfigPublic])
async def list_stage_configs(
    _admin: User = Depends(require_admin),
) -> list[LLMStageConfigPublic]:
    """Return all 10 stage configs, filling in defaults for missing rows."""
    from src.core.container import Container

    repo = Container.llm_config_repo()
    rows = await repo.get_all()
    by_slot = {r.slot_name: r for r in rows}
    return [_row_to_public(stage, by_slot.get(stage)) for stage in STAGES]


@router.put("/{stage}", response_model=LLMStageConfigPublic)
async def update_stage_config(
    stage: str,
    body: UpdateLLMConfigRequest,
    _admin: User = Depends(require_admin),
) -> LLMStageConfigPublic:
    """Upsert the config row for *stage*."""
    if stage not in STAGE_META:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "title": "Unknown stage",
                "status": 404,
                "type": "about:blank",
                "detail": f"Unknown stage: {stage}",
            },
        )

    from src.core.container import Container

    repo = Container.llm_config_repo()
    existing = await repo.get_by_slot(stage)

    if body.api_key is None:
        api_key_encrypted = existing.api_key_encrypted if existing else None
    else:
        api_key_encrypted = body.api_key.encode()

    data: dict[str, Any] = {
        "provider": body.provider,
        "model_name": body.model,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "api_key_encrypted": api_key_encrypted,
    }
    row = await repo.upsert(stage, data)
    return _row_to_public(stage, row)


@router.post("/{stage}/test", response_model=TestConnectionResult)
async def test_stage_connection(
    stage: str,
    _admin: User = Depends(require_admin),
) -> TestConnectionResult:
    """Run a ping call against the stage's provider to verify credentials."""
    if stage not in STAGE_META:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "title": "Unknown stage",
                "status": 404,
                "type": "about:blank",
                "detail": f"Unknown stage: {stage}",
            },
        )

    from src.core.container import Container

    repo = Container.llm_config_repo()
    row = await repo.get_by_slot(stage)
    if row is None or not row.api_key_encrypted:
        return TestConnectionResult(
            success=False,
            latency_ms=0,
            message="No API key configured for this stage",
        )

    try:
        api_key = row.api_key_encrypted.decode("utf-8", errors="replace")
    except Exception:
        return TestConnectionResult(
            success=False,
            latency_ms=0,
            message="Stored API key is unreadable",
        )

    client = AsyncOpenAI(api_key=api_key)
    start = time.monotonic()
    try:
        await client.chat.completions.create(
            model=row.model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
    except Exception as exc:  # noqa: BLE001 - surface safe error
        latency_ms = int((time.monotonic() - start) * 1000)
        message = _scrub(str(exc), api_key)
        return TestConnectionResult(
            success=False,
            latency_ms=latency_ms,
            message=message,
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    return TestConnectionResult(
        success=True,
        latency_ms=latency_ms,
        message="ok",
    )
