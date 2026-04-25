"""Capability defaults indexed by ``(provider, model_id)``.

When a new AIModel row is created, the service looks up this table to
prefill ``capabilities`` (function_calling / vision / json_mode / streaming
/ max_context_tokens / pricing).  Admins may override any entry via PATCH;
unknown ``(provider, model_id)`` pairs default to an empty dict.

This data is intentionally hand-curated.  See §11 of the design doc and
§12 risk #2 for staleness considerations.
"""

from __future__ import annotations

from typing import Any

PROVIDER_MODEL_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    # ---- OpenAI ------------------------------------------------------- #
    ("openai", "gpt-4o"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 128_000,
        "input_cost_per_1m": 2.50,
        "output_cost_per_1m": 10.00,
    },
    ("openai", "gpt-4o-mini"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 128_000,
        "input_cost_per_1m": 0.15,
        "output_cost_per_1m": 0.60,
    },
    ("openai", "gpt-4.1"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 1_000_000,
        "input_cost_per_1m": 2.00,
        "output_cost_per_1m": 8.00,
    },
    ("openai", "o3"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 200_000,
        "input_cost_per_1m": 10.00,
        "output_cost_per_1m": 40.00,
    },
    ("openai", "o4-mini"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 200_000,
        "input_cost_per_1m": 1.10,
        "output_cost_per_1m": 4.40,
    },
    # ---- Anthropic ---------------------------------------------------- #
    ("anthropic", "claude-opus-4-5"): {
        "function_calling": True,
        "vision": True,
        "json_mode": False,
        "streaming": True,
        "max_context_tokens": 200_000,
        "input_cost_per_1m": 15.00,
        "output_cost_per_1m": 75.00,
    },
    ("anthropic", "claude-sonnet-4-6"): {
        "function_calling": True,
        "vision": True,
        "json_mode": False,
        "streaming": True,
        "max_context_tokens": 1_000_000,
        "input_cost_per_1m": 3.00,
        "output_cost_per_1m": 15.00,
    },
    ("anthropic", "claude-haiku-4-5"): {
        "function_calling": True,
        "vision": True,
        "json_mode": False,
        "streaming": True,
        "max_context_tokens": 200_000,
        "input_cost_per_1m": 1.00,
        "output_cost_per_1m": 5.00,
    },
    # ---- Google Gemini ------------------------------------------------ #
    ("google-gemini", "gemini-2.5-pro"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 2_000_000,
        "input_cost_per_1m": 1.25,
        "output_cost_per_1m": 5.00,
    },
    ("google-gemini", "gemini-2.5-flash"): {
        "function_calling": True,
        "vision": True,
        "json_mode": True,
        "streaming": True,
        "max_context_tokens": 1_000_000,
        "input_cost_per_1m": 0.30,
        "output_cost_per_1m": 2.50,
    },
}


def lookup(provider: str, model_id: str) -> dict[str, Any]:
    """Return the capability defaults for ``(provider, model_id)``, or ``{}``."""
    return dict(PROVIDER_MODEL_METADATA.get((provider, model_id), {}))
