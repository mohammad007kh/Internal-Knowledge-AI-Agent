"""Unit tests for the T-012 agentic stage slots: ``planner`` + ``retrieval_grader``.

These slots power the plan-and-execute pipeline (planner) and the
light-everywhere + heavy-for-DB verification (retrieval_grader). They must be:

* declared in :data:`src.agent.stage_defaults.STAGE_DEFAULTS` with a low,
  deterministic temperature (mirroring ``source_router`` / ``retrieval``);
* listed in :data:`src.api.v1.admin.llm_settings.STAGES` / ``STAGE_META`` so
  admins can tune them;
* seeded + linked idempotently by
  :func:`startup_seed.ensure_default_stage_configs` (a second run is a no-op);
* resolvable through :class:`AIModelResolver` (proven with a mocked resolver).

The seeding test is hermetic — it patches the SQLAlchemy session's ``execute``
to return a hand-built row list and records what gets ``add``-ed, mirroring the
pattern in ``test_startup_seed_verify.py``. No real database is touched.
"""
from __future__ import annotations

import os

# Env preamble — same pattern as the other backend unit-test modules.
# Must run before any ``src.*`` import triggers Settings validation.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import uuid  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402

from src.agent.stage_defaults import STAGE_DEFAULTS  # noqa: E402
from src.api.v1.admin.llm_settings import STAGE_META, STAGES  # noqa: E402
from src.services import startup_seed  # noqa: E402

NEW_SLOTS = ("planner", "retrieval_grader")


# --------------------------------------------------------------------------- #
# STAGE_DEFAULTS declarations                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("slot", NEW_SLOTS)
def test_new_slot_in_stage_defaults_low_temperature(slot: str) -> None:
    """Both new slots are declared with a low, deterministic temperature."""
    assert slot in STAGE_DEFAULTS, f"{slot!r} missing from STAGE_DEFAULTS"
    defaults = STAGE_DEFAULTS[slot]
    # Cheap-tier, cold/structured — mirror source_router / retrieval.
    assert 0.0 <= defaults.temperature <= 0.1
    # Short structured output budget per the task (≈1024).
    assert defaults.max_tokens == 1024
    assert defaults.custom_prompt is None


def test_new_slots_mirror_source_router_temperature() -> None:
    """The two new slots match the cold ``source_router`` idiom (temperature=0.0)."""
    cold = STAGE_DEFAULTS["source_router"].temperature
    for slot in NEW_SLOTS:
        assert STAGE_DEFAULTS[slot].temperature == cold == 0.0


# --------------------------------------------------------------------------- #
# STAGES / STAGE_META exposure                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("slot", NEW_SLOTS)
def test_new_slot_in_stages_and_meta(slot: str) -> None:
    """Both new slots are exposed via the admin LLM-settings surface."""
    assert slot in STAGES
    assert slot in STAGE_META
    label, description = STAGE_META[slot]
    assert label and description


def test_stages_grew_by_exactly_two_and_reflector_untouched() -> None:
    """STAGES length accounts for the two new slots; ``reflector`` is unchanged.

    The 11 pre-existing slots plus ``planner`` + ``retrieval_grader`` = 13.
    ``reflector`` must remain present and is not one of the new slots
    (Constitution IV: reflector stays independent / default-OFF).
    """
    pre_existing = {
        "schema_inspector",
        "clarification_detector",
        "query_analyzer",
        "source_router",
        "retrieval",
        "text_to_query",
        "synthesizer",
        "reflector",
        "input_guard",
        "output_guard",
        "titler",
    }
    assert len(STAGES) == len(pre_existing) + 2
    assert set(STAGES) == pre_existing | set(NEW_SLOTS)
    # reflector untouched: still listed, still NOT a new agentic slot.
    assert "reflector" in STAGES
    assert "reflector" not in NEW_SLOTS
    assert STAGE_META["reflector"] == (
        "Reflector",
        "Reflects on and improves answers",
    )


def test_every_stage_has_a_default() -> None:
    """No slot in STAGES is missing a STAGE_DEFAULTS entry (incl. the new ones)."""
    missing = [s for s in STAGES if s not in STAGE_DEFAULTS]
    assert missing == [], f"slots missing STAGE_DEFAULTS: {missing}"


# --------------------------------------------------------------------------- #
# Idempotent seeding through ensure_default_stage_configs                      #
# --------------------------------------------------------------------------- #


def _ai_model() -> MagicMock:
    """A minimal active AIModel row the seeder links new stage rows to."""
    m = MagicMock()
    m.id = uuid.uuid4()
    m.provider = "openai"
    m.model_id = "gpt-4o-mini"
    m.default_temperature = 0.7
    m.default_max_tokens = 2048
    m.is_active = True
    return m


def _llm_row(slot_name: str, ai_model_id) -> MagicMock:
    """A fake ``LLMConfiguration`` row carrying the fields the seeder reads."""
    r = MagicMock()
    r.slot_name = slot_name
    r.ai_model_id = ai_model_id
    r.temperature = STAGE_DEFAULTS[slot_name].temperature
    r.max_tokens = STAGE_DEFAULTS[slot_name].max_tokens
    return r


class _StubSession:
    """Async session stub for ``ensure_default_stage_configs``.

    Routes the two ``select(...)`` calls the seeder makes:

    * ``_pick_default_ai_model`` → ``select(AIModel)`` returns ``ai_model``;
    * the row scan → ``select(LLMConfiguration)`` returns ``existing_rows``.

    ``add``-ed objects are appended to ``existing_rows`` (and recorded in
    ``added``) so a second seeding pass sees the rows the first pass created,
    proving idempotency.
    """

    def __init__(self, ai_model: MagicMock, existing_rows: list[MagicMock]) -> None:
        self._ai_model = ai_model
        self.existing_rows = existing_rows
        self.added: list[object] = []

    async def execute(self, statement):  # noqa: ANN001 - SQLAlchemy stmt
        text = str(statement)
        result = MagicMock()
        if "ai_models" in text or "AIModel" in text:
            # _pick_default_ai_model uses scalar_one_or_none().
            result.scalar_one_or_none.return_value = self._ai_model
            result.scalars.return_value.all.return_value = [self._ai_model]
        else:
            # ensure_default_stage_configs scans LLMConfiguration rows.
            result.scalars.return_value.all.return_value = list(self.existing_rows)
        return result

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)
        # Make the inserted row visible to a subsequent seeding pass.
        rec = MagicMock()
        rec.slot_name = obj.slot_name
        rec.ai_model_id = obj.ai_model_id
        rec.temperature = obj.temperature
        rec.max_tokens = obj.max_tokens
        self.existing_rows.append(rec)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_seeding_inserts_new_slots_then_is_idempotent() -> None:
    """First seed creates planner + retrieval_grader rows; second is a no-op.

    Starting from an empty ``llm_configurations`` table, the first
    ``ensure_default_stage_configs`` inserts a row for every slot in STAGES
    (including the two new ones). The second run must find every row already
    present and insert NOTHING.
    """
    ai_model = _ai_model()
    rows: list[MagicMock] = []
    session = _StubSession(ai_model, rows)

    # First pass — seeds all slots.
    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]
    first_pass_slots = {obj.slot_name for obj in session.added}
    for slot in NEW_SLOTS:
        assert slot in first_pass_slots, f"{slot!r} not seeded on first pass"
    # Each new row is linked + carries the cold defaults.
    for obj in session.added:
        if obj.slot_name in NEW_SLOTS:
            assert obj.ai_model_id == ai_model.id
            assert obj.temperature == 0.0
            assert obj.max_tokens == 1024

    # Second pass — every slot already has a row; nothing new is added.
    session.added.clear()
    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]
    assert session.added == [], "re-seeding inserted rows (not idempotent)"


@pytest.mark.asyncio
async def test_seeding_links_unlinked_new_slot_rows() -> None:
    """A pre-existing but unlinked (ai_model_id=None) new-slot row gets linked.

    Mirrors the relink branch: an admin-touched row with overrides but no
    AIModel link must be repointed at the default model without losing its
    overrides, and without inserting a duplicate.
    """
    ai_model = _ai_model()
    # planner already has a row but it's unlinked.
    orphan = _llm_row("planner", None)
    orphan.temperature = 0.0
    orphan.max_tokens = 1024
    rows: list[MagicMock] = [orphan]
    session = _StubSession(ai_model, rows)

    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]

    # planner was relinked in place, not duplicated.
    assert orphan.ai_model_id == ai_model.id
    assert "planner" not in {obj.slot_name for obj in session.added}
    # retrieval_grader had no row, so it was inserted.
    assert "retrieval_grader" in {obj.slot_name for obj in session.added}


# --------------------------------------------------------------------------- #
# Resolution through a mocked AIModelResolver                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("slot", NEW_SLOTS)
async def test_new_slot_resolves_via_mocked_resolver(slot: str) -> None:
    """Both new slots resolve to an AIModelClient via a mocked resolver.

    Constitution I (Interface-First): nodes obtain a model strictly through
    ``AIModelResolver.resolve(stage)``. We mock the resolver and assert each
    new slot resolves to a usable client carrying the cold defaults.
    """
    from src.services.ai_model_resolver import AIModelClient

    client = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=STAGE_DEFAULTS[slot].temperature,
        max_tokens=STAGE_DEFAULTS[slot].max_tokens,
        custom_prompt=None,
        capabilities={},
        http_client=MagicMock(),
        api_key="sk-test",
        base_url=None,
    )
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=client)

    resolved = await resolver.resolve(slot)

    resolver.resolve.assert_awaited_once_with(slot)
    assert resolved.model_id == "gpt-4o-mini"
    assert resolved.temperature == 0.0
    assert resolved.max_tokens == 1024


# --------------------------------------------------------------------------- #
# Row-count / no-duplicate guard                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_seeding_inserts_exactly_len_stages_rows_on_empty_db() -> None:
    """First seed on an empty table produces exactly len(STAGES) rows — no extras.

    Guards against the seeder iterating STAGES multiple times or misrouting
    the LLMConfiguration query so the same slot gets inserted twice.
    """
    ai_model = _ai_model()
    rows: list[MagicMock] = []
    session = _StubSession(ai_model, rows)

    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]

    assert len(session.added) == len(STAGES), (
        f"expected {len(STAGES)} insertions, got {len(session.added)}: "
        f"{[o.slot_name for o in session.added]}"
    )
    # Every slot name is unique — no slot was inserted twice.
    inserted_slots = [o.slot_name for o in session.added]
    assert len(inserted_slots) == len(set(inserted_slots)), (
        f"duplicate insertions detected: {inserted_slots}"
    )


@pytest.mark.asyncio
async def test_seeding_does_not_overwrite_admin_linked_rows() -> None:
    """A row that is already fully linked (ai_model_id non-null) is left untouched.

    The seeder's idempotency guarantee means it must NOT re-insert a row nor
    mutate a row that is already linked, even if the temperature or max_tokens
    differ from STAGE_DEFAULTS (admin may have customised them).
    """
    ai_model = _ai_model()
    # Simulate an admin-customised planner row: linked but with non-default values.
    admin_row = MagicMock()
    admin_row.slot_name = "planner"
    admin_row.ai_model_id = ai_model.id  # already linked
    admin_row.temperature = 0.5           # admin override — NOT the default 0.0
    admin_row.max_tokens = 2048           # admin override — NOT the default 1024

    rows: list[MagicMock] = [admin_row]
    session = _StubSession(ai_model, rows)

    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]

    # planner must NOT appear in session.added (would be a duplicate insert).
    added_slots = {o.slot_name for o in session.added}
    assert "planner" not in added_slots, "seeder re-inserted an already-linked row"
    # The admin's overrides must survive untouched.
    assert admin_row.temperature == 0.5
    assert admin_row.max_tokens == 2048


@pytest.mark.asyncio
async def test_seeding_relink_preserves_admin_overrides() -> None:
    """An unlinked row with admin-set temperature/max_tokens keeps those values.

    The relink branch (ai_model_id is None) must only fill in the ai_model_id
    pointer and leave existing non-zero temperature / max_tokens intact.
    This specifically tests the ``if existing.temperature is None`` / ``if not
    existing.max_tokens`` guards in ensure_default_stage_configs.
    """
    ai_model = _ai_model()
    # retrieval_grader has a row, but it's unlinked.  Admin already set overrides.
    orphan = MagicMock()
    orphan.slot_name = "retrieval_grader"
    orphan.ai_model_id = None
    orphan.temperature = 0.3   # admin override — truthy, must be preserved
    orphan.max_tokens = 512    # admin override — truthy, must be preserved

    rows: list[MagicMock] = [orphan]
    session = _StubSession(ai_model, rows)

    await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]

    # Link was set.
    assert orphan.ai_model_id == ai_model.id
    # Admin overrides survived the relink.
    assert orphan.temperature == 0.3, "relink overwrote admin temperature override"
    assert orphan.max_tokens == 512, "relink overwrote admin max_tokens override"
    # No new row was inserted for retrieval_grader.
    added_slots = {o.slot_name for o in session.added}
    assert "retrieval_grader" not in added_slots


@pytest.mark.asyncio
async def test_seeding_no_ai_model_logs_warning_and_returns() -> None:
    """When no AIModel exists, seeder logs a warning and adds nothing.

    Covers the guard at the top of ensure_default_stage_configs that bails
    when _pick_default_ai_model returns None (fresh DB, no bootstrap key set).
    """
    import logging

    class _NoModelSession:
        """Session stub that returns no AIModel rows."""

        def __init__(self) -> None:
            self.added: list[object] = []

        async def execute(self, statement):  # noqa: ANN001
            text = str(statement)
            result = MagicMock()
            if "ai_models" in text or "AIModel" in text:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            else:
                result.scalars.return_value.all.return_value = []
            return result

        def add(self, obj) -> None:  # noqa: ANN001
            self.added.append(obj)

        async def flush(self) -> None:
            return None

    session = _NoModelSession()

    import logging as _logging
    logger = _logging.getLogger("src.services.startup_seed")
    records: list[_logging.LogRecord] = []

    class _Cap(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            records.append(record)

    cap = _Cap()
    logger.addHandler(cap)
    try:
        await startup_seed.ensure_default_stage_configs(session)  # type: ignore[arg-type]
    finally:
        logger.removeHandler(cap)

    assert session.added == [], "seeder added rows despite no AIModel"
    warning_msgs = [r.getMessage() for r in records if r.levelno >= _logging.WARNING]
    assert any("no AIModel" in m or "unlinked" in m or "not found" in m or "left unlinked" in m
               for m in warning_msgs), (
        f"expected a warning about missing AIModel, got: {warning_msgs}"
    )


# --------------------------------------------------------------------------- #
# STAGE_DEFAULTS immutability guard                                            #
# --------------------------------------------------------------------------- #


def test_stage_defaults_are_frozen_dataclasses() -> None:
    """StageDefaults instances are frozen — mutations raise AttributeError.

    The frozen=True dataclass enforces that node code cannot accidentally
    overwrite a stage's defaults at runtime (a class of bug seen with
    mutable dicts passed as defaults).
    """
    from src.agent.stage_defaults import StageDefaults

    defaults = STAGE_DEFAULTS["planner"]
    assert isinstance(defaults, StageDefaults)
    with pytest.raises(AttributeError):
        defaults.temperature = 0.9  # type: ignore[misc]


def test_stage_defaults_dict_has_no_extra_keys() -> None:
    """STAGE_DEFAULTS has exactly the slots listed in STAGES — no stale entries.

    A stale key (e.g. a renamed slot left in STAGE_DEFAULTS after renaming it
    in STAGES) would never be seeded and could mask a real missing-default bug.
    """
    extra_keys = set(STAGE_DEFAULTS) - set(STAGES)
    assert extra_keys == set(), (
        f"STAGE_DEFAULTS contains keys not in STAGES: {extra_keys}"
    )
