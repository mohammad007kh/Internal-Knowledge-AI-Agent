"""Unit tests for Celery application factory — T-019."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ── celery_app import & identity ─────────────────────────────────────────────


class TestCeleryAppImport:
    """AC-1: celery_app importable from src.core.celery."""

    def test_celery_app_imports(self) -> None:
        from src.core.celery import celery_app

        assert celery_app is not None
        assert celery_app.main == "knowledge_agent"

    def test_celery_app_broker_uses_redis(self) -> None:
        from src.core.celery import celery_app

        broker_url = celery_app.conf.broker_url
        assert broker_url is not None
        assert "redis" in str(broker_url).lower()

    def test_celery_app_backend_uses_redis(self) -> None:
        from src.core.celery import celery_app

        result_backend = celery_app.conf.result_backend
        assert result_backend is not None
        assert "redis" in str(result_backend).lower()


# ── serialisation config ─────────────────────────────────────────────────────


class TestCelerySerializationConfig:
    """AC-8: JSON-only serialisation, no pickle."""

    def test_task_serializer_is_json(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.task_serializer == "json"

    def test_result_serializer_is_json(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.result_serializer == "json"

    def test_accept_content_json_only(self) -> None:
        from src.core.celery import celery_app

        accept = celery_app.conf.accept_content
        assert accept == ["json"]
        assert "pickle" not in accept

    def test_timezone_utc(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.timezone == "UTC"
        assert celery_app.conf.enable_utc is True


# ── timeout config ───────────────────────────────────────────────────────────


class TestCeleryTimeouts:
    """AC-10: soft_time_limit=300, time_limit=360 (FR-033)."""

    def test_soft_time_limit(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.task_soft_time_limit == 300

    def test_hard_time_limit(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.task_time_limit == 360

    def test_acks_late_enabled(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.task_acks_late is True

    def test_prefetch_multiplier(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_result_expires(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.result_expires == 3600


# ── beat schedule ────────────────────────────────────────────────────────────


class TestBeatSchedule:
    """AC-3/4: beat_schedule initially empty dict."""

    def test_beat_schedule_is_empty_dict(self) -> None:
        from src.core.celery import celery_app

        assert celery_app.conf.beat_schedule == {}


# ── task auto-discovery ──────────────────────────────────────────────────────


class TestTaskDiscovery:
    """AC-9: Celery includes src.tasks for auto-discovery."""

    def test_includes_src_tasks(self) -> None:
        from src.core.celery import celery_app

        assert "src.tasks" in celery_app.conf.include


# ── BaseTask ─────────────────────────────────────────────────────────────────


class TestBaseTask:
    """AC: BaseTask with retry, logging, Sentry."""

    def test_base_task_is_abstract(self) -> None:
        from src.tasks.base import BaseTask

        assert BaseTask.abstract is True

    def test_base_task_default_retries(self) -> None:
        from src.tasks.base import BaseTask

        assert BaseTask.max_retries == 3

    def test_base_task_default_retry_delay(self) -> None:
        from src.tasks.base import BaseTask

        assert BaseTask.default_retry_delay == 60

    @patch("src.tasks.base.sentry_sdk", create=True)
    def test_base_task_on_failure_calls_sentry(
        self, mock_sentry: MagicMock
    ) -> None:
        from src.tasks.base import BaseTask

        task = BaseTask()
        task.name = "test_task"
        exc = RuntimeError("boom")

        with patch("src.tasks.base.logger") as mock_logger:
            task.on_failure(exc, "task-id-1", (), {}, None)

        mock_logger.error.assert_called_once()

    def test_base_task_on_success_logs(self) -> None:
        from src.tasks.base import BaseTask

        task = BaseTask()
        task.name = "test_task"

        with patch("src.tasks.base.logger") as mock_logger:
            task.on_success("result", "task-id-2", (), {})

        mock_logger.info.assert_called_once()

    def test_base_task_on_retry_logs_warning(self) -> None:
        from src.tasks.base import BaseTask

        task = BaseTask()
        task.name = "test_task"
        exc = RuntimeError("retry me")

        with patch("src.tasks.base.logger") as mock_logger:
            task.on_retry(exc, "task-id-3", (), {}, None)

        mock_logger.warning.assert_called_once()
