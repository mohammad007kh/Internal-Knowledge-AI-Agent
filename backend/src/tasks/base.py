"""BaseTask with retry, logging and Sentry integration — T-019.

All project tasks should inherit from ``BaseTask`` to get standardised
error handling, structured logging, and Sentry breadcrumbs for free.

Example
-------
::

    from celery import shared_task
    from src.tasks.base import BaseTask

    @shared_task(base=BaseTask, bind=True, max_retries=5)
    def my_task(self, arg: str) -> dict:
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

logger = logging.getLogger(__name__)


class BaseTask(Task):  # type: ignore[misc]
    """Abstract base for all project tasks.

    Provides:
    * ``on_failure``  — logs error + sends to Sentry
    * ``on_retry``    — logs warning
    * ``on_success``  — logs info
    """

    abstract = True
    max_retries: int = 3
    default_retry_delay: int = 60

    # ── lifecycle callbacks ───────────────────────────────────────────

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        logger.error(
            "Task %s[%s] failed: %s",
            self.name,
            task_id,
            exc,
            exc_info=True,
        )
        try:
            import sentry_sdk  # noqa: PLC0415

            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        logger.warning(
            "Task %s[%s] retrying: %s",
            self.name,
            task_id,
            exc,
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        logger.info("Task %s[%s] succeeded", self.name, task_id)
        super().on_success(retval, task_id, args, kwargs)
