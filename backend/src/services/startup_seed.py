"""Idempotent startup seeding for AI Models, Embedders, and stage configs.

Wired into the FastAPI lifespan in :mod:`src.main` after Redis is up and
before requests are served.  Every step is idempotent — running on each
boot must be a no-op when the DB is already populated.

What it does, in order:

1. **Bootstrap OpenAI AIModel** — if ``ai_models`` is empty AND
   ``settings.OPENAI_API_KEY`` is set, insert a single
   ``"OpenAI (env bootstrap)"`` row using ``gpt-4o-mini`` with the
   capability metadata pulled from
   :mod:`src.services.provider_model_metadata`.  Marked ``is_active=true``
   and editable/deletable by admins (no special "system" flag).
2. **Bootstrap OpenAI Embedder** — if ``embedders`` is empty AND
   ``OPENAI_API_KEY`` is set, insert a single
   ``"OpenAI text-embedding-3-small (env bootstrap)"`` row, 1536-dim,
   ``is_active=true``.
3. **Seed stage configs** — for every slot in
   :data:`src.api.v1.admin.llm_settings.STAGES`, ensure an
   ``llm_configurations`` row exists pointing at *some* AIModel.  When
   ``ai_model_id`` is ``NULL`` (orphaned legacy row), repoint it at the
   default AIModel.  Defaults from :mod:`src.agent.stage_defaults`.

All steps log warnings on failure and continue — a misconfigured DB or
missing key must NOT crash startup.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.stage_defaults import STAGE_DEFAULTS
from src.api.v1.admin.llm_settings import STAGES
from src.core.config import settings
from src.core.crypto import encrypt
from src.core.database import AsyncSessionLocal
from src.models.ai_model import AIModel
from src.models.embedder import Embedder
from src.models.llm_configuration import LLMConfiguration
from src.services.provider_model_metadata import lookup as lookup_capabilities

logger = logging.getLogger(__name__)


# Names of the env-bootstrap rows.  Admins can rename them later — these
# are only used by the seeder to detect "is anything already seeded?".
_BOOTSTRAP_AI_MODEL_NAME = "OpenAI (env bootstrap)"
_BOOTSTRAP_EMBEDDER_NAME = "OpenAI text-embedding-3-small (env bootstrap)"


async def run_startup_seeding() -> None:
    """Top-level entrypoint: bootstrap models + seed stage configs.

    Wraps every logical step so a single failure does not abort the rest
    of the seeding pipeline.  Safe to call on every boot.
    """
    try:
        async with AsyncSessionLocal() as session:
            await _bootstrap_openai_ai_model(session)
            await _bootstrap_openai_embedder(session)
            await ensure_default_stage_configs(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must not fail on seed errors
        logger.warning("startup seeding failed (continuing)", exc_info=True)


# --------------------------------------------------------------------------- #
# AI Model bootstrap                                                          #
# --------------------------------------------------------------------------- #


async def _bootstrap_openai_ai_model(session: AsyncSession) -> None:
    """Insert a single OpenAI AIModel row if the table is empty.

    No-op when:
    * any ``ai_models`` row already exists, OR
    * ``OPENAI_API_KEY`` is unset.
    """
    count = (
        await session.execute(select(func.count()).select_from(AIModel))
    ).scalar_one()
    if count and count > 0:
        return

    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        logger.info(
            "startup seed: OPENAI_API_KEY unset — skipping AIModel bootstrap"
        )
        return

    try:
        encrypted = encrypt(api_key)
    except Exception:  # noqa: BLE001
        logger.warning("startup seed: encrypt(OPENAI_API_KEY) failed", exc_info=True)
        return

    capabilities = lookup_capabilities("openai", "gpt-4o-mini")

    row = AIModel(
        name=_BOOTSTRAP_AI_MODEL_NAME,
        provider="openai",
        base_url=None,
        model_id="gpt-4o-mini",
        api_key_encrypted=encrypted,
        extra_config={},
        default_temperature=0.7,
        default_max_tokens=2048,
        capabilities=capabilities or {},
        is_active=True,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "startup seed: created bootstrap AIModel name=%r model_id=%s",
        _BOOTSTRAP_AI_MODEL_NAME,
        "gpt-4o-mini",
    )


# --------------------------------------------------------------------------- #
# Embedder bootstrap                                                          #
# --------------------------------------------------------------------------- #


async def _bootstrap_openai_embedder(session: AsyncSession) -> None:
    """Insert a single OpenAI Embedder row if the table is empty.

    No-op when ``embedders`` already has rows or the key is unset.
    """
    count = (
        await session.execute(select(func.count()).select_from(Embedder))
    ).scalar_one()
    if count and count > 0:
        return

    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        logger.info(
            "startup seed: OPENAI_API_KEY unset — skipping Embedder bootstrap"
        )
        return

    try:
        encrypted = encrypt(api_key)
    except Exception:  # noqa: BLE001
        logger.warning(
            "startup seed: encrypt(OPENAI_API_KEY) failed for embedder",
            exc_info=True,
        )
        return

    row = Embedder(
        name=_BOOTSTRAP_EMBEDDER_NAME,
        provider="openai",
        base_url=None,
        model_id="text-embedding-3-small",
        api_key_encrypted=encrypted,
        extra_config={},
        dimensions=1536,
        max_input_tokens=8191,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "startup seed: created bootstrap Embedder name=%r dim=%d",
        _BOOTSTRAP_EMBEDDER_NAME,
        1536,
    )


# --------------------------------------------------------------------------- #
# Stage config seeding                                                        #
# --------------------------------------------------------------------------- #


async def ensure_default_stage_configs(session: AsyncSession) -> None:
    """Ensure every pipeline stage has a non-null ``ai_model_id`` row.

    For each stage in ``STAGES``:

    * If no ``llm_configurations`` row exists for the slot, insert one
      with the per-stage defaults from :data:`STAGE_DEFAULTS` linked to
      the default AIModel.
    * If a row exists but ``ai_model_id`` is ``NULL``, link it to the
      default AIModel (preserving any existing temperature / max_tokens
      overrides the admin may have set).

    The "default AIModel" is resolved once per call as the first active
    row, falling back to the first row of any kind.  When no AIModel
    exists at all the function logs a warning and returns — the seeded
    rows can be linked later via the admin UI.

    Idempotent: running twice is safe.
    """
    default_ai_model = await _pick_default_ai_model(session)
    if default_ai_model is None:
        logger.warning(
            "startup seed: no AIModel rows found — stage configs left unlinked"
        )
        return

    existing_rows = (
        await session.execute(select(LLMConfiguration))
    ).scalars().all()
    by_slot: dict[str, LLMConfiguration] = {r.slot_name: r for r in existing_rows}

    inserted = 0
    relinked = 0
    for stage in STAGES:
        defaults = STAGE_DEFAULTS.get(stage)
        if defaults is None:
            # Stage listed in STAGES but missing from STAGE_DEFAULTS — log and
            # fall back to the AIModel's own defaults.
            logger.warning(
                "startup seed: no STAGE_DEFAULTS entry for stage %r — using model defaults",
                stage,
            )
            temperature = default_ai_model.default_temperature
            max_tokens = default_ai_model.default_max_tokens
            custom_prompt = None
        else:
            temperature = defaults.temperature
            max_tokens = defaults.max_tokens
            custom_prompt = defaults.custom_prompt

        existing = by_slot.get(stage)
        if existing is None:
            row = LLMConfiguration(
                slot_name=stage,
                ai_model_id=default_ai_model.id,
                temperature=temperature,
                max_tokens=max_tokens,
                custom_prompt=custom_prompt,
                # Legacy mirror columns — kept in sync until the R3 drop.
                provider=default_ai_model.provider,
                model_name=default_ai_model.model_id,
                is_default=False,
            )
            session.add(row)
            inserted += 1
        elif existing.ai_model_id is None:
            existing.ai_model_id = default_ai_model.id
            existing.provider = default_ai_model.provider
            existing.model_name = default_ai_model.model_id
            # Only fill numeric overrides when they're missing/zero — admins
            # may have already changed them on a partially configured row.
            if existing.temperature is None:
                existing.temperature = temperature
            if not existing.max_tokens:
                existing.max_tokens = max_tokens
            relinked += 1

    if inserted or relinked:
        await session.flush()
        logger.info(
            "startup seed: stage configs inserted=%d relinked=%d (total stages=%d)",
            inserted,
            relinked,
            len(STAGES),
        )


async def _pick_default_ai_model(session: AsyncSession) -> AIModel | None:
    """Return the AIModel row used for fresh stage seeds.

    Preference order: first ``is_active=True`` row, else first row of any
    kind, else ``None``.
    """
    active = (
        await session.execute(
            select(AIModel).where(AIModel.is_active.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return active
    return (
        await session.execute(select(AIModel).limit(1))
    ).scalar_one_or_none()
