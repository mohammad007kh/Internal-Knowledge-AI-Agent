"""LLM configuration service — manages per-slot and per-source LLM settings.

Implements FR-LLM-* requirements.

Encryption is delegated to :mod:`src.core.crypto`, replacing the previous
no-op stub that historically stored plaintext API keys (security CRITICAL,
fixed as part of the AI Models & Embedders rollout).
"""
from __future__ import annotations

import uuid
from typing import Any

from src.core.crypto import encrypt as _fernet_encrypt
from src.core.exceptions import NotFoundError


class LLMConfigService:
    """Manages LLM configuration slots (provider / model / temperature / api-key).

    Args:
        llm_repo: Repository providing access to
            :class:`~src.models.llm_configuration.LLMConfiguration` records.
    """

    def __init__(self, llm_repo: Any) -> None:
        self._repo = llm_repo

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_slot(
        self,
        slot_name: str,
        provider: str,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        api_key: str | None = None,
        is_default: bool = False,
        source_id: uuid.UUID | None = None,
    ) -> Any:
        """Create a new LLM configuration slot.

        The *api_key*, if provided, is encrypted before storage via
        :func:`_encrypt_value`.

        Args:
            slot_name: Unique human-readable name for the slot.
            provider: LLM provider identifier (e.g. ``"openai"``).
            model_name: Provider-specific model name.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens per completion.
            api_key: Plain-text API key — encrypted before persistence.
            is_default: When ``True`` this slot is the system-wide default.
            source_id: Optional source override — overrides the default for
                a specific knowledge source.

        Returns:
            The newly created
            :class:`~src.models.llm_configuration.LLMConfiguration` instance.
        """
        encrypted_key: bytes | None = None
        if api_key is not None:
            encrypted_key = _encrypt_value(api_key)

        return await self._repo.create(
            {
                "slot_name": slot_name,
                "provider": provider,
                "model_name": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "api_key_encrypted": encrypted_key,
                "is_default": is_default,
                "source_id": source_id,
            }
        )

    async def update_slot(self, slot_id: uuid.UUID, **kwargs: Any) -> Any:
        """Update an existing LLM slot.

        Args:
            slot_id: UUID of the slot to update.
            **kwargs: Fields to update.

        Returns:
            Updated :class:`~src.models.llm_configuration.LLMConfiguration`.

        Raises:
            :exc:`~src.core.exceptions.NotFoundError`: When *slot_id* is unknown.
        """
        existing = await self._repo.get_by_id(slot_id)
        if existing is None:
            raise NotFoundError(f"LLM slot {slot_id} not found.")

        if "api_key" in kwargs:
            raw = kwargs.pop("api_key")
            kwargs["api_key_encrypted"] = _encrypt_value(raw) if raw else None

        return await self._repo.update(slot_id, kwargs)

    async def delete_slot(self, slot_id: uuid.UUID) -> None:
        """Delete an LLM configuration slot.

        Raises:
            :exc:`~src.core.exceptions.NotFoundError`: When *slot_id* is unknown.
        """
        existing = await self._repo.get_by_id(slot_id)
        if existing is None:
            raise NotFoundError(f"LLM slot {slot_id} not found.")
        await self._repo.delete(slot_id)

    # ------------------------------------------------------------------
    # Hot-reload / lookup
    # ------------------------------------------------------------------

    async def get_default_slot(self) -> Any:
        """Return the current default LLM configuration slot.

        Returns:
            The default :class:`~src.models.llm_configuration.LLMConfiguration`,
            or ``None`` when no default has been configured.
        """
        return await self._repo.get_default()

    async def set_source_override(
        self,
        source_id: uuid.UUID,
        slot_id: uuid.UUID,
    ) -> Any:
        """Associate a specific LLM slot with a knowledge source.

        If the slot does not exist a :exc:`~src.core.exceptions.NotFoundError`
        is raised.  Otherwise the slot's ``source_id`` is set to *source_id*.

        Args:
            source_id: UUID of the knowledge source.
            slot_id: UUID of the LLM configuration slot.

        Returns:
            Updated :class:`~src.models.llm_configuration.LLMConfiguration`.
        """
        existing = await self._repo.get_by_id(slot_id)
        if existing is None:
            raise NotFoundError(f"LLM slot {slot_id} not found.")
        return await self._repo.upsert_source_override(source_id, slot_id)

    async def get_slot_for_source(self, source_id: uuid.UUID) -> Any:
        """Return the LLM slot for *source_id*, falling back to the default.

        Returns:
            The per-source :class:`~src.models.llm_configuration.LLMConfiguration`
            if one exists, otherwise the system default (possibly ``None``).
        """
        override = await self._repo.get_by_source_id(source_id)
        if override is not None:
            return override
        return await self._repo.get_default()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encrypt_value(plain_text: str) -> bytes:
    """Encrypt *plain_text* with the project Fernet key.

    Delegates to :func:`src.core.crypto.encrypt` — the single source of truth
    for symmetric secret storage across the codebase.
    """
    return _fernet_encrypt(plain_text)
