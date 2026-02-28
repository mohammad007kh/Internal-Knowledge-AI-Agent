"""Connector registry: ``@register`` decorator and ``get_connector`` factory (T-045).

Concrete connectors self-register by decorating their class::

    from src.connectors.registry import register
    from src.models.enums import SourceType

    @register(SourceType.WEB_URL)
    class WebUrlConnector(BaseConnector):
        ...

``get_connector`` then instantiates the appropriate class on demand.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.models.enums import SourceType

from .base import BaseConnector

# ------------------------------------------------------------------ #
# Registry storage
# ------------------------------------------------------------------ #

CONNECTOR_REGISTRY: dict[SourceType, type[BaseConnector]] = {}

# ------------------------------------------------------------------ #
# Public helpers
# ------------------------------------------------------------------ #


def register(
    source_type: SourceType,
) -> Callable[[type[BaseConnector]], type[BaseConnector]]:
    """
    Class decorator that maps *source_type* to the decorated connector class.

    Raises ``RuntimeError`` if the same ``SourceType`` is registered more than once
    to catch accidental double-import side-effects.

    Example::

        @register(SourceType.WEB_URL)
        class WebUrlConnector(BaseConnector):
            ...
    """

    def decorator(cls: type[BaseConnector]) -> type[BaseConnector]:
        if source_type in CONNECTOR_REGISTRY:
            raise RuntimeError(
                f"Connector for {source_type!r} is already registered "
                f"as {CONNECTOR_REGISTRY[source_type].__name__!r}."
            )
        CONNECTOR_REGISTRY[source_type] = cls
        return cls

    return decorator


def get_connector(source_type: SourceType, config: dict[str, Any]) -> BaseConnector:
    """
    Look up the connector class for *source_type*, instantiate it with *config*,
    and return the new instance.

    Raises ``ValueError`` if no connector has been registered for the given type.
    This is a programming error (likely a missing import in ``__init__.py``).
    """
    cls = CONNECTOR_REGISTRY.get(source_type)
    if cls is None:
        registered = ", ".join(t.value for t in CONNECTOR_REGISTRY)
        raise ValueError(
            f"No connector registered for source_type={source_type!r}. "
            f"Registered types: [{registered}]"
        )
    return cls(config)
