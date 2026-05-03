"""Unit tests for ``src.services.provider_catalog``.

These tests pin the response contract for ``GET /api/v1/admin/providers``.
The frontend (``frontend/src/types/provider.ts``) consumes the merged
``providers: ProviderSpec[]`` shape, so the keys and per-entry fields tested
here must stay in lock-step with that file.
"""

from __future__ import annotations

import pytest

from src.services.provider_catalog import (
    EMBEDDER_PROVIDERS,
    LLM_PROVIDERS,
    PROVIDER_FAMILY,
    PROVIDERS_WITHOUT_NATIVE_EMBEDDER,
    build_catalog_payload,
)


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


def test_payload_has_single_providers_key() -> None:
    """Frontend expects ``{providers: [...]}``; nothing else."""
    payload = build_catalog_payload()
    assert set(payload.keys()) == {"providers"}
    assert isinstance(payload["providers"], list)
    assert len(payload["providers"]) > 0


def test_each_provider_carries_required_fields() -> None:
    """Every entry must satisfy the frontend ``ProviderSpec`` interface."""
    required = {
        "key",
        "display",
        "family_tag",
        "default_base_url",
        "base_url_required",
        "auth_scheme",
        "extra_fields",
        "llm_models",
        "embedder_models",
        "embedder_unsupported",
    }
    payload = build_catalog_payload()
    for entry in payload["providers"]:
        missing = required - entry.keys()
        assert not missing, f"{entry['key']} missing fields: {missing}"


def test_provider_keys_are_unique() -> None:
    payload = build_catalog_payload()
    keys = [p["key"] for p in payload["providers"]]
    assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"


# ---------------------------------------------------------------------------
# Per-entry semantics
# ---------------------------------------------------------------------------


def test_llm_models_have_model_id_and_label() -> None:
    payload = build_catalog_payload()
    for entry in payload["providers"]:
        for suggestion in entry["llm_models"]:
            assert "model_id" in suggestion
            assert "label" in suggestion
            assert isinstance(suggestion["model_id"], str)


def test_embedder_models_have_dimensions() -> None:
    payload = build_catalog_payload()
    for entry in payload["providers"]:
        for suggestion in entry["embedder_models"]:
            assert "model_id" in suggestion
            assert "dimensions" in suggestion
            assert isinstance(suggestion["dimensions"], int)
            assert suggestion["dimensions"] > 0


def test_anthropic_marked_embedder_unsupported() -> None:
    payload = build_catalog_payload()
    by_key = {p["key"]: p for p in payload["providers"]}
    assert by_key["anthropic"]["embedder_unsupported"] is True
    assert by_key["anthropic"]["embedder_models"] == []


def test_openai_has_both_llms_and_embedders() -> None:
    payload = build_catalog_payload()
    by_key = {p["key"]: p for p in payload["providers"]}
    openai = by_key["openai"]
    assert openai["embedder_unsupported"] is False
    assert len(openai["llm_models"]) > 0
    assert len(openai["embedder_models"]) > 0


def test_v1_locked_dimension_present() -> None:
    """At least one OpenAI embedder must declare the v1-locked 1536 dim."""
    payload = build_catalog_payload()
    by_key = {p["key"]: p for p in payload["providers"]}
    dims = {m["dimensions"] for m in by_key["openai"]["embedder_models"]}
    assert 1536 in dims, "v1 invariant: 1536-dim embedder must be available"


def test_family_tags_consistent_with_module_constant() -> None:
    payload = build_catalog_payload()
    for entry in payload["providers"]:
        assert entry["family_tag"] == PROVIDER_FAMILY[entry["key"]]


# ---------------------------------------------------------------------------
# Backwards-compat: legacy dicts still exposed for any in-repo consumers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["openai", "anthropic", "google-gemini", "azure-openai", "ollama", "openai-compatible"],
)
def test_legacy_llm_dict_exposes_known_keys(key: str) -> None:
    assert key in LLM_PROVIDERS
    spec = LLM_PROVIDERS[key]
    assert spec["key"] == key
    assert "auth_style" in spec  # legacy field name


@pytest.mark.parametrize(
    "key",
    ["openai", "google-gemini", "voyage", "cohere", "ollama"],
)
def test_legacy_embedder_dict_exposes_known_keys(key: str) -> None:
    assert key in EMBEDDER_PROVIDERS
    spec = EMBEDDER_PROVIDERS[key]
    assert spec["key"] == key
    assert "configurable_dimensions" in spec


def test_anthropic_in_no_native_embedder_set() -> None:
    assert "anthropic" in PROVIDERS_WITHOUT_NATIVE_EMBEDDER
