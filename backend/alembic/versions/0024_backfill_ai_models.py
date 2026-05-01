"""Backfill ai_models / embedders from existing llm_configurations + env defaults.

R2 — data-only migration:

* Insert a single ``embedders`` row ``legacy-openai-1536`` (1536-dim text-embedding-3-small),
  Fernet-encrypted with ``settings.OPENAI_API_KEY``.  Mark it ``is_active = true``.
* For every distinct ``(provider, model_name, api_key_encrypted)`` tuple in
  ``llm_configurations`` insert a corresponding ``ai_models`` row.  When the
  existing ``api_key_encrypted`` is the legacy plaintext (no Fernet header),
  decode it as UTF-8 and re-encrypt with the real Fernet helper.
* Backfill ``sources.embedder_id`` and ``chunks.embedder_id`` to point at the
  legacy row, in 10k-row batches.
* Backfill ``llm_configurations.ai_model_id`` from the matching insert.

This revision MUST run after R1 (0023) and before R3 (the tighten phase).

Revision ID: 0024
Revises:     0023
Create Date: 2026-04-25
"""

from __future__ import annotations

import logging
import os
import uuid

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger(__name__)

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels = None
depends_on = None

LEGACY_EMBEDDER_NAME = "legacy-openai-1536"


def _encrypt(plain: str) -> bytes:
    """Encrypt with the project Fernet key — local import keeps the migration
    runnable in environments where the full app may not be importable."""
    from cryptography.fernet import Fernet  # noqa: PLC0415

    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY env var must be set for migration 0024")
    return Fernet(key.encode()).encrypt(plain.encode("utf-8"))


def _try_decrypt(blob: bytes) -> str | None:
    from cryptography.fernet import Fernet, InvalidToken  # noqa: PLC0415

    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode()).decrypt(blob).decode("utf-8")
    except InvalidToken:
        return None
    except Exception:  # noqa: BLE001
        return None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------ #
    # 1. Insert legacy embedder (idempotent on re-run).                    #
    # ------------------------------------------------------------------ #
    openai_key = os.environ.get("OPENAI_API_KEY") or ""
    api_key_encrypted = _encrypt(openai_key) if openai_key else None

    legacy_id_row = bind.execute(
        sa.text("SELECT id FROM embedders WHERE name = :n"),
        {"n": LEGACY_EMBEDDER_NAME},
    ).first()
    if legacy_id_row is None:
        legacy_id = uuid.uuid4()
        bind.execute(
            sa.text(
                """
                INSERT INTO embedders
                  (id, name, provider, base_url, model_id,
                   api_key_encrypted, extra_config, dimensions,
                   max_input_tokens, is_active)
                VALUES
                  (:id, :name, 'openai', NULL, 'text-embedding-3-small',
                   :api_key, '{}', 1536, 8191, true)
                """
            ),
            {"id": legacy_id, "name": LEGACY_EMBEDDER_NAME, "api_key": api_key_encrypted},
        )
    else:
        legacy_id = legacy_id_row[0]

    # ------------------------------------------------------------------ #
    # 2. For each distinct llm_configurations tuple, insert an ai_model.   #
    # ------------------------------------------------------------------ #
    rows = bind.execute(
        sa.text(
            """
            SELECT id, slot_name, provider, model_name, api_key_encrypted,
                   temperature, max_tokens
            FROM llm_configurations
            WHERE ai_model_id IS NULL
              AND provider IS NOT NULL
              AND model_name IS NOT NULL
            """
        )
    ).fetchall()

    seen: dict[tuple[str, str, bytes | None], uuid.UUID] = {}
    for row in rows:
        provider = row.provider
        model_name = row.model_name
        existing_blob: bytes | None = row.api_key_encrypted

        # Re-encrypt legacy plaintext stub if present.
        if existing_blob is not None:
            decrypted = _try_decrypt(existing_blob)
            if decrypted is None:
                # Treat as legacy plaintext (the no-op stub stored bytes).
                try:
                    plaintext = existing_blob.decode("utf-8")
                    existing_blob = _encrypt(plaintext)
                except Exception:  # noqa: BLE001
                    existing_blob = None

        key_tuple = (provider, model_name, existing_blob)
        ai_id = seen.get(key_tuple)
        if ai_id is None:
            ai_id = uuid.uuid4()
            ai_name = f"{provider}-{model_name}-{row.slot_name}"[:150]
            # Avoid name collisions on retry by appending a short uuid suffix.
            existing_name = bind.execute(
                sa.text("SELECT 1 FROM ai_models WHERE name = :n"),
                {"n": ai_name},
            ).first()
            if existing_name is not None:
                ai_name = f"{ai_name[:140]}-{str(ai_id)[:6]}"

            try:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO ai_models
                          (id, name, provider, base_url, model_id,
                           api_key_encrypted, extra_config, default_temperature,
                           default_max_tokens, capabilities, is_active)
                        VALUES
                          (:id, :name, :provider, NULL, :model_id,
                           :api_key, '{}', :temp, :max_tokens, '{}', true)
                        """
                    ),
                    {
                        "id": ai_id,
                        "name": ai_name,
                        "provider": provider,
                        "model_id": model_name,
                        "api_key": existing_blob,
                        "temp": row.temperature or 0.7,
                        "max_tokens": row.max_tokens or 2048,
                    },
                )
            except Exception:  # noqa: BLE001
                # Likely UX_ai_models_provider_model unique conflict — pick the existing row.
                logger.exception(
                    "ai_models insert failed for %s/%s — looking up existing",
                    provider,
                    model_name,
                )
                existing = bind.execute(
                    sa.text(
                        """
                        SELECT id FROM ai_models
                        WHERE provider = :p AND model_id = :m
                        LIMIT 1
                        """
                    ),
                    {"p": provider, "m": model_name},
                ).first()
                if existing is None:
                    raise
                ai_id = existing[0]
            seen[key_tuple] = ai_id

        bind.execute(
            sa.text(
                "UPDATE llm_configurations SET ai_model_id = :ai_id WHERE id = :id"
            ),
            {"ai_id": ai_id, "id": row.id},
        )

    # ------------------------------------------------------------------ #
    # 3. Backfill sources.embedder_id and chunks.embedder_id (10k batches) #
    # ------------------------------------------------------------------ #
    _batch_update_null(
        bind,
        table="sources",
        pk="id",
        set_clause="embedder_id = :emb",
        where_clause="embedder_id IS NULL",
        params={"emb": legacy_id},
        batch_size=10_000,
    )
    _batch_update_null(
        bind,
        table="chunks",
        pk="id",
        set_clause="embedder_id = :emb",
        where_clause="embedder_id IS NULL",
        params={"emb": legacy_id},
        batch_size=10_000,
    )


def _batch_update_null(
    bind: sa.engine.Connection,  # type: ignore[name-defined]
    *,
    table: str,
    pk: str,
    set_clause: str,
    where_clause: str,
    params: dict,
    batch_size: int,
) -> None:
    """UPDATE rows matching *where_clause* in batches of *batch_size*."""
    while True:
        result = bind.execute(
            sa.text(
                f"""
                WITH batch AS (
                    SELECT {pk} FROM {table}
                    WHERE {where_clause}
                    LIMIT {batch_size}
                )
                UPDATE {table}
                SET {set_clause}
                WHERE {pk} IN (SELECT {pk} FROM batch)
                """
            ),
            params,
        )
        if result.rowcount == 0:
            break


def downgrade() -> None:
    """Best-effort rollback — clears the FKs but keeps the legacy rows.

    This is intentionally lossy: the source-of-truth API keys have been
    re-encrypted, so reverting could discard credentials.  Operators wanting
    a true rollback should restore from a pre-R2 backup.
    """
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE chunks SET embedder_id = NULL"))
    bind.execute(sa.text("UPDATE sources SET embedder_id = NULL"))
    bind.execute(sa.text("UPDATE llm_configurations SET ai_model_id = NULL"))
