"""Celery application factory (T-064).

The module-level ``celery_app`` singleton is imported by worker processes
and by task modules to register their tasks.

Task modules MUST be listed in ``include=`` below so the worker imports them
at startup and the ``@celery_app.task`` decorators run. ``autodiscover_tasks``
is unsuitable here because it looks for a ``tasks`` submodule in each listed
package (i.e. ``src.tasks.tasks``), which does not exist — task functions live
in sibling modules such as ``sync_source.py``.
"""
from __future__ import annotations

from celery import Celery

from src.core.config import settings

# Every task module MUST be added here. send_task("tasks.X") fails silently
# (KeyError on the worker) if its defining module isn't imported at startup.
TASK_MODULES: list[str] = [
    "src.tasks.sync_source",
    "src.tasks.check_scheduled_syncs",
    "src.tasks.trigger_all_syncs",
    "src.tasks.auto_name_source",
]

celery_app: Celery = Celery(
    "knowledge_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=TASK_MODULES,
)
celery_app.config_from_object("src.tasks.celeryconfig")
