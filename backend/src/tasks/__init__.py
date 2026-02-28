"""Celery application factory (T-064).

The module-level ``celery_app`` singleton is imported by worker processes
and by ``sync_source.py`` to register the task.
"""
from __future__ import annotations

from celery import Celery

from src.core.config import settings

celery_app: Celery = Celery(
    "knowledge_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.config_from_object("src.tasks.celeryconfig")
celery_app.autodiscover_tasks(["src.tasks"])
