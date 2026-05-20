"""Per-stage LLM tuning defaults for the 10 admin pipeline slots.

Source-of-truth for the seeded ``LLMConfiguration`` rows written by
:func:`src.services.startup_seed.ensure_default_stage_configs` on app
startup.  Each entry is a ``(temperature, max_tokens, custom_prompt)``
triple keyed by the slot name listed in
:data:`src.api.v1.admin.llm_settings.STAGES`.

Admins can edit any of these via ``PUT /admin/llm-settings/{stage}`` once
the row is seeded — this dict only defines the *initial* values for a
fresh row.  Updating a value here does NOT retroactively rewrite a row
that already exists; that's intentional so admin overrides stick.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDefaults:
    """Immutable defaults applied when a stage row is first seeded."""

    temperature: float
    max_tokens: int
    custom_prompt: str | None = None


# Conservative defaults — guards/extractors run cold (temperature=0.0) so they
# behave deterministically; rewriters and synthesisers get more headroom.
STAGE_DEFAULTS: dict[str, StageDefaults] = {
    # Schema / structural inspection — deterministic, mid-size output.
    "schema_inspector": StageDefaults(temperature=0.1, max_tokens=2048),
    # Clarification gate — short JSON-style verdicts.
    "clarification_detector": StageDefaults(temperature=0.0, max_tokens=512),
    # Query rewriting / classification.
    "query_analyzer": StageDefaults(temperature=0.3, max_tokens=1024),
    # Source routing — short structured output.
    "source_router": StageDefaults(temperature=0.0, max_tokens=512),
    # Retrieval re-ranking / grading — short structured output.
    "retrieval": StageDefaults(temperature=0.0, max_tokens=1024),
    # Natural language → structured query (SQL/Cypher/etc).
    "text_to_query": StageDefaults(temperature=0.0, max_tokens=1024),
    # Final answer generation — most permissive.
    "synthesizer": StageDefaults(temperature=0.7, max_tokens=2048),
    # Reflector / self-critic — slightly creative but bounded.
    "reflector": StageDefaults(temperature=0.3, max_tokens=1024),
    # Safety guards — fully deterministic, very short verdicts.
    "input_guard": StageDefaults(temperature=0.0, max_tokens=256),
    "output_guard": StageDefaults(temperature=0.0, max_tokens=256),
    # Auto-titler — short sidebar-style titles for new chat sessions.
    # Mildly creative but bounded; ~30 tokens covers a 3–7 word title.
    "titler": StageDefaults(temperature=0.3, max_tokens=30, custom_prompt=None),
}
