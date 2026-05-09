"""Unit tests for SchemaStudy / SchemaStudyPhase ORM models.

All tests are sync and require NO database — they assert column metadata,
defaults, FK declarations, ondelete=CASCADE wiring, and relationship
configuration.

Pattern matches ``backend/tests/unit/test_user_models.py``.
"""

from __future__ import annotations

import uuid

from src.models.schema_study import (
    PHASE_STATUSES,
    STUDY_PHASES,
    STUDY_STATES,
    SchemaStudy,
    SchemaStudyPhase,
)
from src.models.source import Source


# ===================================================================
# Vocabulary constants
# ===================================================================


class TestVocabularies:
    """The exported state/phase sets must contain every spec value."""

    def test_study_states_contains_terminal_ready(self) -> None:
        assert "READY" in STUDY_STATES
        assert "READY_PARTIAL" in STUDY_STATES

    def test_study_states_contains_phase_failures(self) -> None:
        for failure in (
            "CONNECT_FAILED",
            "INVENTORY_FAILED",
            "COLUMNS_FAILED",
            "SAMPLING_FAILED",
            "DESCRIBING_FAILED",
            "INDEXING_FAILED",
        ):
            assert failure in STUDY_STATES, f"missing {failure}"

    def test_study_phases_count(self) -> None:
        assert STUDY_PHASES == frozenset(
            {"CONNECTING", "INVENTORY", "COLUMNS", "SAMPLING", "DESCRIBING", "INDEXING"}
        )

    def test_phase_statuses_count(self) -> None:
        assert PHASE_STATUSES == frozenset(
            {"pending", "running", "success", "failed", "skipped", "timeout"}
        )


# ===================================================================
# SchemaStudy — column metadata
# ===================================================================


class TestSchemaStudyColumns:
    cols = SchemaStudy.__table__.columns

    def test_tablename(self) -> None:
        assert SchemaStudy.__tablename__ == "schema_studies"

    def test_id_column_exists(self) -> None:
        assert "id" in self.cols

    def test_source_id_column_exists(self) -> None:
        assert "source_id" in self.cols

    def test_source_id_has_fk_to_sources(self) -> None:
        fks = self.cols["source_id"].foreign_keys
        assert len(fks) == 1
        fk = next(iter(fks))
        assert fk.target_fullname == "sources.id"

    def test_source_id_fk_cascades_on_delete(self) -> None:
        """Deleting a source MUST cascade-delete its studies."""
        fk = next(iter(self.cols["source_id"].foreign_keys))
        assert fk.ondelete == "CASCADE"

    def test_source_id_indexed(self) -> None:
        assert self.cols["source_id"].index is True

    def test_state_column_exists(self) -> None:
        assert "state" in self.cols

    def test_state_indexed(self) -> None:
        assert self.cols["state"].index is True

    def test_state_not_nullable(self) -> None:
        assert self.cols["state"].nullable is False

    def test_fingerprint_nullable(self) -> None:
        assert self.cols["fingerprint"].nullable is True

    def test_schema_document_json_nullable(self) -> None:
        assert self.cols["schema_document_json"].nullable is True

    def test_agent_version_not_nullable(self) -> None:
        assert self.cols["agent_version"].nullable is False

    def test_started_at_not_nullable(self) -> None:
        assert self.cols["started_at"].nullable is False

    def test_finished_at_nullable(self) -> None:
        assert self.cols["finished_at"].nullable is True

    def test_partial_not_nullable(self) -> None:
        assert self.cols["partial"].nullable is False

    def test_last_error_phase_nullable(self) -> None:
        assert self.cols["last_error_phase"].nullable is True

    def test_last_error_message_nullable(self) -> None:
        assert self.cols["last_error_message"].nullable is True

    def test_timestamps_present(self) -> None:
        # TimestampMixin
        assert "created_at" in self.cols
        assert "updated_at" in self.cols


# ===================================================================
# SchemaStudy — defaults / construction
# ===================================================================


class TestSchemaStudyDefaults:
    def test_explicit_id_respected(self) -> None:
        explicit = uuid.uuid4()
        study = SchemaStudy(
            id=explicit,
            source_id=uuid.uuid4(),
            agent_version="1.0.0",
        )
        assert study.id == explicit

    def test_state_defaults_to_queued(self) -> None:
        col = SchemaStudy.__table__.columns["state"]
        assert col.default.arg == "QUEUED"

    def test_partial_defaults_to_false(self) -> None:
        col = SchemaStudy.__table__.columns["partial"]
        assert col.default.arg is False


# ===================================================================
# SchemaStudy — relationships + cascade
# ===================================================================


class TestSchemaStudyRelationships:
    def test_phases_relationship_exists(self) -> None:
        assert hasattr(SchemaStudy, "phases")

    def test_phases_relationship_cascades(self) -> None:
        rel = SchemaStudy.__mapper__.relationships["phases"]
        # ``delete-orphan`` and ``delete`` must both be present.
        cascade = str(rel.cascade)
        assert "delete" in cascade
        assert "delete-orphan" in cascade


# ===================================================================
# SchemaStudyPhase — column metadata
# ===================================================================


class TestSchemaStudyPhaseColumns:
    cols = SchemaStudyPhase.__table__.columns

    def test_tablename(self) -> None:
        assert SchemaStudyPhase.__tablename__ == "schema_study_phases"

    def test_id_exists(self) -> None:
        assert "id" in self.cols

    def test_study_id_has_fk(self) -> None:
        fks = self.cols["study_id"].foreign_keys
        assert len(fks) == 1
        fk = next(iter(fks))
        assert fk.target_fullname == "schema_studies.id"

    def test_study_id_fk_cascades(self) -> None:
        fk = next(iter(self.cols["study_id"].foreign_keys))
        assert fk.ondelete == "CASCADE"

    def test_phase_not_nullable(self) -> None:
        assert self.cols["phase"].nullable is False

    def test_status_not_nullable(self) -> None:
        assert self.cols["status"].nullable is False

    def test_status_default_is_pending(self) -> None:
        col = SchemaStudyPhase.__table__.columns["status"]
        assert col.default.arg == "pending"

    def test_error_columns_nullable(self) -> None:
        assert self.cols["error_key"].nullable is True
        assert self.cols["error_message"].nullable is True

    def test_started_finished_nullable(self) -> None:
        assert self.cols["started_at"].nullable is True
        assert self.cols["finished_at"].nullable is True

    def test_progress_columns_nullable(self) -> None:
        assert self.cols["progress_n"].nullable is True
        assert self.cols["progress_total"].nullable is True

    def test_composite_index_on_study_phase(self) -> None:
        names = {idx.name for idx in SchemaStudyPhase.__table__.indexes}
        assert "ix_schema_study_phases_study_phase" in names


# ===================================================================
# Source — Phase 1 columns added
# ===================================================================


class TestSourcePhase1Columns:
    cols = Source.__table__.columns

    def test_schema_status_column_added(self) -> None:
        assert "schema_status" in self.cols

    def test_schema_status_nullable(self) -> None:
        assert self.cols["schema_status"].nullable is True

    def test_schema_status_indexed(self) -> None:
        assert self.cols["schema_status"].index is True

    def test_drift_signal_count_column_added(self) -> None:
        assert "drift_signal_count" in self.cols

    def test_drift_signal_count_not_nullable(self) -> None:
        assert self.cols["drift_signal_count"].nullable is False

    def test_drift_signal_count_default_zero(self) -> None:
        assert self.cols["drift_signal_count"].default.arg == 0

    def test_last_studied_at_column_added(self) -> None:
        assert "last_studied_at" in self.cols

    def test_last_studied_at_nullable(self) -> None:
        assert self.cols["last_studied_at"].nullable is True


# ===================================================================
# to_dict
# ===================================================================


class TestSchemaStudyToDict:
    def test_returns_dict(self) -> None:
        s = SchemaStudy(source_id=uuid.uuid4(), agent_version="1.0.0")
        d = s.to_dict()
        assert isinstance(d, dict)
        for col in (
            "id",
            "source_id",
            "state",
            "fingerprint",
            "schema_document_json",
            "agent_version",
            "started_at",
            "finished_at",
            "partial",
            "last_error_phase",
            "last_error_message",
            "created_at",
            "updated_at",
        ):
            assert col in d, f"missing {col}"
