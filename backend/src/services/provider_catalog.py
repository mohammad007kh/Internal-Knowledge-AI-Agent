"""Static provider catalog for the AI Models / Embedders admin UI.

Every entry exposes the provider's display name, default base URL, an
``auth_style`` hint, the suggested model identifiers, and the extra config
fields required for that provider.  The frontend hydrates dropdowns from
``GET /api/v1/admin/providers``.

The ``family_tag`` field drives the cosmetic "often paired with…" hint in
the embedder picker.  It is **never** validated server-side.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ProviderSpec(TypedDict, total=False):
    key: str
    display: str
    family_tag: str
    default_base_url: str | None
    auth_style: str
    suggested_models: list[str]
    extra_fields: list[str]
    notes: str


class EmbedderProviderSpec(TypedDict, total=False):
    key: str
    display: str
    family_tag: str
    default_base_url: str | None
    auth_style: str
    suggested_models: list[dict[str, Any]]
    configurable_dimensions: bool
    notes: str


# v1 LLM providers — see §5 of the design doc.
LLM_PROVIDERS: dict[str, ProviderSpec] = {
    "openai": {
        "key": "openai",
        "display": "OpenAI",
        "family_tag": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "auth_style": "bearer",
        "suggested_models": [
            "gpt-4.1",
            "gpt-4o",
            "gpt-4o-mini",
            "o3",
            "o4-mini",
        ],
        "extra_fields": ["organization_id", "project_id"],
    },
    "anthropic": {
        "key": "anthropic",
        "display": "Anthropic",
        "family_tag": "anthropic",
        "default_base_url": "https://api.anthropic.com/v1",
        "auth_style": "x-api-key",
        "suggested_models": [
            "claude-opus-4-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ],
        "extra_fields": ["anthropic_version"],
        "notes": "x-api-key header + anthropic-version header (default 2023-06-01)",
    },
    "google-gemini": {
        "key": "google-gemini",
        "display": "Google Gemini (AI Studio)",
        "family_tag": "google",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "auth_style": "x-goog-api-key",
        "suggested_models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "extra_fields": [],
    },
    "azure-openai": {
        "key": "azure-openai",
        "display": "Azure OpenAI",
        "family_tag": "openai",
        "default_base_url": None,
        "auth_style": "api-key",
        "suggested_models": [],
        "extra_fields": ["azure_endpoint", "deployment_name", "api_version"],
        "notes": "Base URL is composed from azure_endpoint + deployment_name",
    },
    "ollama": {
        "key": "ollama",
        "display": "Ollama (local)",
        "family_tag": "local",
        "default_base_url": "http://ollama:11434/v1",
        "auth_style": "none",
        "suggested_models": ["llama3.3", "qwen2.5", "mistral-nemo"],
        "extra_fields": [],
    },
    "openai-compatible": {
        "key": "openai-compatible",
        "display": "OpenAI-compatible",
        "family_tag": "compatible",
        "default_base_url": None,
        "auth_style": "bearer-optional",
        "suggested_models": [],
        "extra_fields": [],
        "notes": "Use for vLLM, LiteLLM, TGI, Vertex compat shim, etc.",
    },
}

# v1 Embedder providers — model entries carry their native dimensions.
EMBEDDER_PROVIDERS: dict[str, EmbedderProviderSpec] = {
    "openai": {
        "key": "openai",
        "display": "OpenAI",
        "family_tag": "openai",
        "default_base_url": "https://api.openai.com/v1",
        "auth_style": "bearer",
        "suggested_models": [
            {"model_id": "text-embedding-3-small", "dimensions": 1536, "configurable": True},
            {"model_id": "text-embedding-3-large", "dimensions": 3072, "configurable": True},
            {"model_id": "text-embedding-ada-002", "dimensions": 1536, "configurable": False},
        ],
        "configurable_dimensions": True,
    },
    "google-gemini": {
        "key": "google-gemini",
        "display": "Google Gemini",
        "family_tag": "google",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "auth_style": "x-goog-api-key",
        "suggested_models": [
            {"model_id": "gemini-embedding-001", "dimensions": 3072, "configurable": True},
            {"model_id": "text-embedding-004", "dimensions": 768, "configurable": True},
        ],
        "configurable_dimensions": True,
    },
    "voyage": {
        "key": "voyage",
        "display": "Voyage AI",
        "family_tag": "voyage",
        "default_base_url": "https://api.voyageai.com/v1",
        "auth_style": "bearer",
        "suggested_models": [
            {"model_id": "voyage-3-large", "dimensions": 1024, "configurable": False},
            {"model_id": "voyage-3", "dimensions": 1024, "configurable": False},
            {"model_id": "voyage-3-lite", "dimensions": 512, "configurable": False},
            {"model_id": "voyage-code-3", "dimensions": 1024, "configurable": False},
        ],
        "configurable_dimensions": False,
    },
    "cohere": {
        "key": "cohere",
        "display": "Cohere",
        "family_tag": "cohere",
        "default_base_url": "https://api.cohere.com/v2",
        "auth_style": "bearer",
        "suggested_models": [
            {"model_id": "embed-v4.0", "dimensions": 1536, "configurable": True},
            {"model_id": "embed-english-v3.0", "dimensions": 1024, "configurable": False},
            {"model_id": "embed-multilingual-v3.0", "dimensions": 1024, "configurable": False},
        ],
        "configurable_dimensions": True,
    },
    "azure-openai": {
        "key": "azure-openai",
        "display": "Azure OpenAI",
        "family_tag": "openai",
        "default_base_url": None,
        "auth_style": "api-key",
        "suggested_models": [],
        "configurable_dimensions": True,
    },
    "ollama": {
        "key": "ollama",
        "display": "Ollama (local)",
        "family_tag": "local",
        "default_base_url": "http://ollama:11434/v1",
        "auth_style": "none",
        "suggested_models": [
            {"model_id": "nomic-embed-text", "dimensions": 768, "configurable": False},
            {"model_id": "mxbai-embed-large", "dimensions": 1024, "configurable": False},
            {"model_id": "bge-m3", "dimensions": 1024, "configurable": False},
        ],
        "configurable_dimensions": False,
    },
    "openai-compatible": {
        "key": "openai-compatible",
        "display": "OpenAI-compatible",
        "family_tag": "compatible",
        "default_base_url": None,
        "auth_style": "bearer-optional",
        "suggested_models": [],
        "configurable_dimensions": True,
    },
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

PROVIDERS_WITHOUT_NATIVE_EMBEDDER: frozenset[str] = frozenset({"anthropic"})


def build_catalog_payload() -> dict[str, Any]:
    """Build the JSON payload returned by ``GET /api/v1/admin/providers``."""
    return {
        "llm_providers": list(LLM_PROVIDERS.values()),
        "embedder_providers": list(EMBEDDER_PROVIDERS.values()),
        "family_tags": PROVIDER_FAMILY,
        "providers_without_native_embedder": sorted(PROVIDERS_WITHOUT_NATIVE_EMBEDDER),
    }
