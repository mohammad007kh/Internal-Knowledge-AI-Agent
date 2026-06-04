"""Unit tests for the agentic-pipeline (004) settings in src.core.config.

These flags are the single source of truth for the plan-and-execute agent's
rollout switch (FR-026) and hard caps that bound every turn's cost (FR-019).
The defaults MUST land on a fully-disabled, conservatively-bounded posture:
agent OFF, deadline guard disabled (None), and the documented numeric caps.
"""

import os

import pytest

from src.core.config import Settings

# Minimal set of required (no-default) fields so Settings() can be built in
# isolation without a live .env. Values are throwaway test fixtures.
_REQUIRED_FIELDS = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/test",
    "JWT_SECRET_KEY": "test-secret",
    "JWT_REFRESH_SECRET_KEY": "test-refresh-secret",
    "MINIO_ACCESS_KEY": "test-access",
    "MINIO_SECRET_KEY": "test-secret-key",
    "ENCRYPTION_KEY": "test-encryption-key",
}


def _build_settings(**overrides: object) -> Settings:
    return Settings(**{**_REQUIRED_FIELDS, **overrides})  # type: ignore[arg-type]


def test_agentic_pipeline_disabled_by_default() -> None:
    """Rollout flag (FR-026) defaults OFF."""
    settings = _build_settings()
    assert settings.PIPELINE_AGENTIC_ENABLED is False


def test_agent_hard_caps_have_documented_defaults() -> None:
    """The bounded-cost hard caps (FR-019) match the data-model defaults."""
    settings = _build_settings()
    assert settings.AGENT_MAX_PLAN_STEPS == 5
    assert settings.AGENT_MAX_PLAN_REVISIONS == 1
    assert settings.AGENT_MAX_STEP_RETRIES == 1


def test_agent_token_ceilings_have_seed_defaults() -> None:
    """Token ceilings default to the documented seed values."""
    settings = _build_settings()
    assert settings.AGENT_TOKEN_CEILING_INPUT == 30000
    assert settings.AGENT_TOKEN_CEILING_OUTPUT == 4000


def test_agent_turn_deadline_disabled_by_default() -> None:
    """Wall-clock guard is a nullable int defaulting to None (disabled)."""
    settings = _build_settings()
    assert settings.AGENT_TURN_DEADLINE_SECS is None


def test_agent_caps_are_correct_types() -> None:
    """Caps are ints (bool flag stays bool); deadline is Optional[int]."""
    settings = _build_settings()
    assert isinstance(settings.PIPELINE_AGENTIC_ENABLED, bool)
    assert isinstance(settings.AGENT_MAX_PLAN_STEPS, int)
    assert isinstance(settings.AGENT_MAX_PLAN_REVISIONS, int)
    assert isinstance(settings.AGENT_MAX_STEP_RETRIES, int)
    assert isinstance(settings.AGENT_TOKEN_CEILING_INPUT, int)
    assert isinstance(settings.AGENT_TOKEN_CEILING_OUTPUT, int)


def test_agent_turn_deadline_accepts_explicit_int() -> None:
    """A concrete deadline (set at rollout) is honored as an int."""
    settings = _build_settings(AGENT_TURN_DEADLINE_SECS=45)
    assert settings.AGENT_TURN_DEADLINE_SECS == 45


# ---------------------------------------------------------------------------
# Regression guards: env-var override behavior (Pydantic Settings reads env)
# ---------------------------------------------------------------------------


def test_pipeline_agentic_enabled_env_var_true_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """PIPELINE_AGENTIC_ENABLED='true' in env coerces to bool True.

    Pydantic Settings resolves env vars before kwargs; the string 'true'
    must be correctly parsed to the Python bool True.  This guards against
    the bool-coercion being silently broken by a type-annotation change.
    """
    monkeypatch.setenv("PIPELINE_AGENTIC_ENABLED", "true")
    settings = _build_settings()
    assert settings.PIPELINE_AGENTIC_ENABLED is True
    assert isinstance(settings.PIPELINE_AGENTIC_ENABLED, bool)


def test_pipeline_agentic_enabled_env_var_false_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """PIPELINE_AGENTIC_ENABLED='false' in env keeps the bool False default."""
    monkeypatch.setenv("PIPELINE_AGENTIC_ENABLED", "false")
    settings = _build_settings()
    assert settings.PIPELINE_AGENTIC_ENABLED is False


def test_agent_max_plan_steps_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_MAX_PLAN_STEPS read from env overrides the coded default of 5."""
    monkeypatch.setenv("AGENT_MAX_PLAN_STEPS", "10")
    settings = _build_settings()
    assert settings.AGENT_MAX_PLAN_STEPS == 10


def test_agent_turn_deadline_env_var_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_TURN_DEADLINE_SECS set via env var is parsed to int (not None)."""
    monkeypatch.setenv("AGENT_TURN_DEADLINE_SECS", "60")
    settings = _build_settings()
    assert settings.AGENT_TURN_DEADLINE_SECS == 60
    assert isinstance(settings.AGENT_TURN_DEADLINE_SECS, int)


def test_agent_turn_deadline_env_var_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_TURN_DEADLINE_SECS=0 from env is accepted as int 0 (not None).

    Zero is a valid (if extreme) deadline; it must not be collapsed to None
    through falsy coercion in the validator.
    """
    monkeypatch.setenv("AGENT_TURN_DEADLINE_SECS", "0")
    settings = _build_settings()
    assert settings.AGENT_TURN_DEADLINE_SECS == 0
    assert isinstance(settings.AGENT_TURN_DEADLINE_SECS, int)


# ---------------------------------------------------------------------------
# Regression guard: making AGENT_TURN_DEADLINE_SECS non-nullable would FAIL
# these tests, catching the regression described in the review scope.
# ---------------------------------------------------------------------------


def test_agent_turn_deadline_non_nullable_regression() -> None:
    """If AGENT_TURN_DEADLINE_SECS were made non-nullable (int, not int|None)
    the default would have to be a concrete int, not None.  This test pins
    the None default so a type-annotation narrowing is caught immediately.
    """
    settings = _build_settings()
    # Must be exactly None — not 0, not -1.
    assert settings.AGENT_TURN_DEADLINE_SECS is None
    # Type check: None is not an int.
    assert not isinstance(settings.AGENT_TURN_DEADLINE_SECS, int)


# ---------------------------------------------------------------------------
# Regression guard: changing a default value would FAIL these specific
# single-field tests, making the breakage obvious rather than buried.
# ---------------------------------------------------------------------------


def test_pipeline_agentic_enabled_default_is_exactly_false() -> None:
    """PIPELINE_AGENTIC_ENABLED default must be False (not a truthy non-bool)."""
    settings = _build_settings()
    assert settings.PIPELINE_AGENTIC_ENABLED is False  # identity, not equality


def test_agent_max_plan_steps_default_is_exactly_5() -> None:
    """Default of 5 is load-bearing per FR-019; changing it is a breaking change."""
    assert _build_settings().AGENT_MAX_PLAN_STEPS == 5


def test_agent_max_plan_revisions_default_is_exactly_1() -> None:
    """Default of 1 revision per FR-019."""
    assert _build_settings().AGENT_MAX_PLAN_REVISIONS == 1


def test_agent_max_step_retries_default_is_exactly_1() -> None:
    """Default of 1 retry per FR-019."""
    assert _build_settings().AGENT_MAX_STEP_RETRIES == 1


def test_agent_token_ceiling_input_default_is_exactly_30000() -> None:
    """Input token ceiling seed value per R9 documentation."""
    assert _build_settings().AGENT_TOKEN_CEILING_INPUT == 30000


def test_agent_token_ceiling_output_default_is_exactly_4000() -> None:
    """Output token ceiling seed value per R9 documentation."""
    assert _build_settings().AGENT_TOKEN_CEILING_OUTPUT == 4000
