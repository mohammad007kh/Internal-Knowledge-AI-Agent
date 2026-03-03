"""Structured JSON logging configuration."""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.core.config import settings


def configure_logging(level: str | None = None) -> None:
    """Configure structlog for structured JSON output and wire stdlib logging."""
    _level = level or settings.LOG_LEVEL

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, _level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.handlers = [handler]


def get_logger(name: str = __name__) -> Any:
    return structlog.get_logger(name)
