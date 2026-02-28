"""Celery configuration constants (T-064).

Imported via ``celery_app.config_from_object("src.tasks.celeryconfig")``.
All values follow the ``task_*`` / ``worker_*`` / ``result_*`` naming
convention introduced in Celery 4 (the old UPPER-CASE names are deprecated).
"""
from __future__ import annotations

# ── Serialisation ────────────────────────────────────────────────────────────
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]

# ── Reliability ───────────────────────────────────────────────────────────────
task_acks_late = True  # ACK only after successful execution
task_reject_on_worker_lost = True  # Re-queue if worker vanishes mid-task

# ── Retry defaults ────────────────────────────────────────────────────────────
task_default_retry_delay = 60  # seconds

# ── Worker behaviour ─────────────────────────────────────────────────────────
worker_prefetch_multiplier = 1  # One task at a time per worker process
worker_max_tasks_per_child = 50  # Recycle worker after 50 tasks (memory safety)

# ── Time limits ───────────────────────────────────────────────────────────────
task_soft_time_limit = 600  # 10 min  — raises SoftTimeLimitExceeded
task_time_limit = 660  # 11 min  — hard kill

# ── Results ───────────────────────────────────────────────────────────────────
result_expires = 86_400  # 24 h  — backend keeps result for 1 day

# ── Routing ───────────────────────────────────────────────────────────────────
task_default_queue = "default"
