"""Stage capability requirements + compatibility checker.

The frontend AI-model picker uses ``is_compatible`` (via API) to disable
incompatible models with an explanatory tooltip.  See §11 of the design doc.
"""

from __future__ import annotations

from typing import Any

# Stage → required capability dict.  Boolean entries require ``cap == True``;
# ``min_context_tokens`` is a numeric lower bound.
STAGE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "source_router": {"function_calling": True, "min_context_tokens": 8_000},
    "query_classifier": {"json_mode": True, "min_context_tokens": 4_000},
    "retrieval_grader": {"json_mode": True, "min_context_tokens": 4_000},
    "answer_generator": {"streaming": True, "min_context_tokens": 16_000},
    "summarizer": {"min_context_tokens": 32_000},
}


def is_compatible(caps: dict[str, Any], stage: str) -> tuple[bool, list[str]]:
    """Return ``(ok, missing)`` indicating compatibility of *caps* with *stage*.

    Args:
        caps: The AI model's capability dict (as stored on
            :class:`~src.models.ai_model.AIModel.capabilities`).
        stage: Stage key (matches an entry in :data:`STAGE_REQUIREMENTS`).

    Returns:
        ``(True, [])`` when every requirement is satisfied; otherwise
        ``(False, [missing capability strings])``.  Unknown stages return
        ``(True, [])`` (not enforced).
    """
    requirements = STAGE_REQUIREMENTS.get(stage)
    if not requirements:
        return True, []

    missing: list[str] = []
    for key, required_value in requirements.items():
        if key == "min_context_tokens":
            actual = caps.get("max_context_tokens")
            if actual is None or int(actual) < int(required_value):
                missing.append(f"min_context_tokens>={required_value}")
            continue
        if required_value is True and not caps.get(key):
            missing.append(key)
    return (len(missing) == 0), missing
