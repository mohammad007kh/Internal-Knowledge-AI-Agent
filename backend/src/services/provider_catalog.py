"""Static provider catalog for the AI Models / Embedders admin UI.

Every entry exposes the provider's display name, default base URL, an
``auth_scheme`` hint, the suggested LLM and embedder model identifiers, and
the extra config fields required for that provider.  The frontend hydrates
dropdowns from ``GET /api/v1/admin/providers``.

The ``family_tag`` field drives the cosmetic "often paired with…" hint in
the embedder picker.  It is **never** validated server-side.

Response shape contract — must stay aligned with
``frontend/src/types/provider.ts::ProviderCatalog``::

    {
      "providers": [
        {
          "key": str,
          "display": str,
          "family_tag": str,
          "default_base_url": str | None,
          "base_url_required": bool,
          "auth_scheme": str | None,
          "extra_fields": list[str],
          "llm_models": list[ProviderModelSuggestion],
          "embedder_models": list[ProviderModelSuggestion],
          "embedder_unsupported": bool,
        },
        ...
      ]
    }

Tests covering the shape live in
``backend/tests/unit/test_provider_catalog.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class _LlmEntry:
    """Per-provider LLM metadata."""

    default_base_url: str | None
    auth_scheme: str
    suggested_models: tuple[str, ...]
    extra_fields: tuple[str, ...] = ()
    notes: str | None = None
    base_url_required: bool = False


@dataclass(frozen=True)
class _EmbedderModel:
    model_id: str
    dimensions: int
    configurable: bool = False


@dataclass(frozen=True)
class _EmbedderEntry:
    """Per-provider embedder metadata."""

    default_base_url: str | None
    auth_scheme: str
    suggested_models: tuple[_EmbedderModel, ...]
    configurable_dimensions: bool = False
    base_url_required: bool = False


@dataclass(frozen=True)
class _ProviderEntry:
    """Merged provider entry shipped to the frontend."""

    key: str
    display: str
    family_tag: str
    default_base_url: str | None
    auth_scheme: str
    base_url_required: bool = False
    extra_fields: tuple[str, ...] = ()
    llm_models: tuple[str, ...] = ()
    embedder_models: tuple[_EmbedderModel, ...] = field(default_factory=tuple)
    embedder_unsupported: bool = False
    notes: str | None = None


# v1 LLM providers — see §5 of the design doc.
_LLM_PROVIDERS: dict[str, _LlmEntry] = {
    "openai": _LlmEntry(
        default_base_url="https://api.openai.com/v1",
        auth_scheme="bearer",
        suggested_models=("gpt-4.1", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini"),
        extra_fields=("organization_id", "project_id"),
    ),
    "anthropic": _LlmEntry(
        default_base_url="https://api.anthropic.com/v1",
        auth_scheme="x-api-key",
        suggested_models=("claude-opus-4-5", "claude-sonnet-4-6", "claude-haiku-4-5"),
        extra_fields=("anthropic_version",),
        notes="x-api-key header + anthropic-version header (default 2023-06-01)",
    ),
    "google-gemini": _LlmEntry(
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        auth_scheme="x-goog-api-key",
        suggested_models=("gemini-2.5-pro", "gemini-2.5-flash"),
    ),
    "azure-openai": _LlmEntry(
        default_base_url=None,
        auth_scheme="api-key",
        suggested_models=(),
        extra_fields=("azure_endpoint", "deployment_name", "api_version"),
        notes="Base URL is composed from azure_endpoint + deployment_name",
        base_url_required=True,
    ),
    "ollama": _LlmEntry(
        default_base_url="http://ollama:11434/v1",
        auth_scheme="none",
        suggested_models=("llama3.3", "qwen2.5", "mistral-nemo"),
    ),
    "openai-compatible": _LlmEntry(
        default_base_url=None,
        auth_scheme="bearer-optional",
        suggested_models=(),
        notes="Use for vLLM, LiteLLM, TGI, Vertex compat shim, etc.",
        base_url_required=True,
    ),
}


# v1 Embedder providers — model entries carry their native dimensions.
_EMBEDDER_PROVIDERS: dict[str, _EmbedderEntry] = {
    "openai": _EmbedderEntry(
        default_base_url="https://api.openai.com/v1",
        auth_scheme="bearer",
        suggested_models=(
            _EmbedderModel("text-embedding-3-small", 1536, True),
            _EmbedderModel("text-embedding-3-large", 3072, True),
            _EmbedderModel("text-embedding-ada-002", 1536, False),
        ),
        configurable_dimensions=True,
    ),
    "google-gemini": _EmbedderEntry(
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        auth_scheme="x-goog-api-key",
        suggested_models=(
            _EmbedderModel("gemini-embedding-001", 3072, True),
            _EmbedderModel("text-embedding-004", 768, True),
        ),
        configurable_dimensions=True,
    ),
    "voyage": _EmbedderEntry(
        default_base_url="https://api.voyageai.com/v1",
        auth_scheme="bearer",
        suggested_models=(
            _EmbedderModel("voyage-3-large", 1024, False),
            _EmbedderModel("voyage-3", 1024, False),
            _EmbedderModel("voyage-3-lite", 512, False),
            _EmbedderModel("voyage-code-3", 1024, False),
        ),
        configurable_dimensions=False,
    ),
    "cohere": _EmbedderEntry(
        default_base_url="https://api.cohere.com/v2",
        auth_scheme="bearer",
        suggested_models=(
            _EmbedderModel("embed-v4.0", 1536, True),
            _EmbedderModel("embed-english-v3.0", 1024, False),
            _EmbedderModel("embed-multilingual-v3.0", 1024, False),
        ),
        configurable_dimensions=True,
    ),
    "azure-openai": _EmbedderEntry(
        default_base_url=None,
        auth_scheme="api-key",
        suggested_models=(),
        configurable_dimensions=True,
        base_url_required=True,
    ),
    "ollama": _EmbedderEntry(
        default_base_url="http://ollama:11434/v1",
        auth_scheme="none",
        suggested_models=(
            _EmbedderModel("nomic-embed-text", 768, False),
            _EmbedderModel("mxbai-embed-large", 1024, False),
            _EmbedderModel("bge-m3", 1024, False),
        ),
        configurable_dimensions=False,
    ),
    "openai-compatible": _EmbedderEntry(
        default_base_url=None,
        auth_scheme="bearer-optional",
        suggested_models=(),
        configurable_dimensions=True,
        base_url_required=True,
    ),
}


# Soft pairing hints — used only for cosmetic UX warnings (never validation).
PROVIDER_FAMILY: dict[str, str] = {
    "openai": "openai",
    "azure-openai": "openai",
    "anthropic": "anthropic",
    "google-gemini": "google",
    "voyage": "voyage",
    "cohere": "cohere",
    "ollama": "local",
    "openai-compatible": "compatible",
}


# Display names — single source of truth so admin UIs stay consistent.
_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google-gemini": "Google Gemini (AI Studio)",
    "azure-openai": "Azure OpenAI",
    "ollama": "Ollama (local)",
    "openai-compatible": "OpenAI-compatible",
    "voyage": "Voyage AI",
    "cohere": "Cohere",
}


PROVIDERS_WITHOUT_NATIVE_EMBEDDER: frozenset[str] = frozenset({"anthropic"})


# ---------------------------------------------------------------------------
# Backwards-compat: legacy modules still import these dict shapes.  Build
# them lazily from the merged source-of-truth so we do not drift again.
# ---------------------------------------------------------------------------


def _legacy_llm_dict() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, entry in _LLM_PROVIDERS.items():
        item: dict[str, Any] = {
            "key": key,
            "display": _DISPLAY_NAMES[key],
            "family_tag": PROVIDER_FAMILY[key],
            "default_base_url": entry.default_base_url,
            "auth_style": entry.auth_scheme,
            "suggested_models": list(entry.suggested_models),
            "extra_fields": list(entry.extra_fields),
        }
        if entry.notes:
            item["notes"] = entry.notes
        out[key] = item
    return out


def _legacy_embedder_dict() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, entry in _EMBEDDER_PROVIDERS.items():
        item: dict[str, Any] = {
            "key": key,
            "display": _DISPLAY_NAMES[key],
            "family_tag": PROVIDER_FAMILY[key],
            "default_base_url": entry.default_base_url,
            "auth_style": entry.auth_scheme,
            "suggested_models": [
                {
                    "model_id": m.model_id,
                    "dimensions": m.dimensions,
                    "configurable": m.configurable,
                }
                for m in entry.suggested_models
            ],
            "configurable_dimensions": entry.configurable_dimensions,
        }
        out[key] = item
    return out


# Eagerly materialised — modules elsewhere import these dicts at import time.
LLM_PROVIDERS: dict[str, dict[str, Any]] = _legacy_llm_dict()
EMBEDDER_PROVIDERS: dict[str, dict[str, Any]] = _legacy_embedder_dict()


# ---------------------------------------------------------------------------
# Merged catalog — what the frontend actually consumes.
# ---------------------------------------------------------------------------


def _suggestion_for_llm(model_id: str) -> dict[str, Any]:
    """LLM model suggestions ship without `dimensions`."""
    return {"model_id": model_id, "label": model_id}


def _suggestion_for_embedder(model: _EmbedderModel) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "label": model.model_id,
        "dimensions": model.dimensions,
    }


def _merge_keys() -> list[str]:
    """Stable display order: LLM-first then embedder-only providers."""
    seen: set[str] = set()
    ordered: list[str] = []
    for key in _LLM_PROVIDERS:
        if key not in seen:
            ordered.append(key)
            seen.add(key)
    for key in _EMBEDDER_PROVIDERS:
        if key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def _build_provider_entry(key: str) -> dict[str, Any]:
    llm = _LLM_PROVIDERS.get(key)
    emb = _EMBEDDER_PROVIDERS.get(key)

    # Prefer the LLM entry's metadata when both exist; fall back to the
    # embedder entry.  When only one exists, that one wins outright.
    base_source = llm or emb
    if base_source is None:
        # Defensive — _merge_keys() guarantees one side exists.
        raise RuntimeError(f"provider {key!r} has neither LLM nor embedder entry")

    default_base_url = base_source.default_base_url
    auth_scheme = base_source.auth_scheme
    base_url_required = base_source.base_url_required

    extra_fields: tuple[str, ...] = ()
    notes: str | None = None
    if isinstance(base_source, _LlmEntry):
        extra_fields = base_source.extra_fields
        notes = base_source.notes

    llm_models = (
        [_suggestion_for_llm(m) for m in llm.suggested_models] if llm is not None else []
    )
    embedder_models = (
        [_suggestion_for_embedder(m) for m in emb.suggested_models] if emb is not None else []
    )

    embedder_unsupported = key in PROVIDERS_WITHOUT_NATIVE_EMBEDDER

    entry: dict[str, Any] = {
        "key": key,
        "display": _DISPLAY_NAMES[key],
        "family_tag": PROVIDER_FAMILY[key],
        "default_base_url": default_base_url,
        "base_url_required": base_url_required,
        "auth_scheme": auth_scheme,
        "extra_fields": list(extra_fields),
        "llm_models": llm_models,
        "embedder_models": embedder_models,
        "embedder_unsupported": embedder_unsupported,
    }
    if notes:
        entry["notes"] = notes
    return entry


def build_catalog_payload() -> dict[str, Any]:
    """Build the JSON payload returned by ``GET /api/v1/admin/providers``.

    Returns the merged shape consumed by the frontend
    (``frontend/src/types/provider.ts::ProviderCatalog``)::

        { "providers": [ ProviderSpec, ... ] }

    Each ``ProviderSpec`` carries both ``llm_models`` and ``embedder_models``
    (either may be empty), plus the ``embedder_unsupported`` flag for
    providers without a native embedder offering (e.g. Anthropic).
    """
    return {
        "providers": [_build_provider_entry(key) for key in _merge_keys()],
    }
