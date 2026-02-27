"""Celery task definitions — stub for T-035 tests.

Real tasks defined in T-042 (document processing pipeline) and
T-061 (scheduled beat tasks).

The ``celery_app`` instance is imported from ``src.core.celery``
so the single app object is shared across the entire codebase.
"""
from src.core.celery import celery_app  # noqa: F401 — re-exported for patching

__all__ = ["celery_app"]
