"""Celery application factory — T-019.

Creates the Celery app instance used by workers, beat, and
``@shared_task`` decorators throughout the codebase.

Usage
-----
Worker CMD::

    celery -A src.core.celery:celery_app worker --loglevel=info --concurrency=4

Beat CMD::

    celery -A src.core.celery:celery_app beat --loglevel=info \
        --scheduler celery.beat:PersistentScheduler
"""

from celery import Celery

from src.core.config import settings

celery_app = Celery(
    "knowledge_agent",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.tasks"],
)

celery_app.conf.update(
    # ── Serialisation — JSON only, no pickle ──────────────────────────
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # ── Timezone ──────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,
    # ── Reliability ───────────────────────────────────────────────────
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # ── Timeouts (FR-033) ─────────────────────────────────────────────
    task_soft_time_limit=300,
    task_time_limit=360,
    # ── Result backend ────────────────────────────────────────────────
    result_expires=3600,
    # ── Beat schedule — populated by T-061 ────────────────────────────
    beat_schedule={},
)
