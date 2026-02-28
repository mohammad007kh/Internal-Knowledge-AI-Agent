"""Connector package — concrete connectors are imported here for ``@register`` side-effects (T-045).

Public surface::

    from src.connectors import BaseConnector, Document, CONNECTOR_REGISTRY, get_connector, register

Concrete connectors are intentionally commented out until their tasks are complete.
Un-comment each import as the corresponding task lands:
"""
from .base import BaseConnector, Document
from .registry import CONNECTOR_REGISTRY, get_connector, register

# Concrete connectors — imported solely for registration side-effect.
# Un-comment as each task is completed:
# from . import web_url_connector      # noqa: F401 — T-046
# from . import file_upload_connector  # noqa: F401 — T-047
# from . import database_connector     # noqa: F401 — T-048
# from . import confluence_connector   # noqa: F401 — T-049
# from . import sharepoint_connector   # noqa: F401 — T-049

__all__ = [
    "BaseConnector",
    "Document",
    "CONNECTOR_REGISTRY",
    "get_connector",
    "register",
]
