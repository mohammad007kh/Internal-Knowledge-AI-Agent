"""Connector package — imports register all concrete connectors into CONNECTOR_REGISTRY.

Import order does not matter; each connector self-registers via @register().

Public surface::

    from src.connectors import (
        BaseConnector, Document, CONNECTOR_REGISTRY, get_connector, register,
        ConfluenceConnector, DatabaseConnector, FileUploadConnector,
        SharePointConnector, WebUrlConnector,
    )
"""
from src.connectors.base import BaseConnector, Document

# Concrete implementations — side-effect imports trigger @register()
from src.connectors.confluence_connector import ConfluenceConnector  # noqa: F401
from src.connectors.database_connector import DatabaseConnector  # noqa: F401
from src.connectors.file_upload_connector import FileUploadConnector  # noqa: F401
from src.connectors.registry import CONNECTOR_REGISTRY, get_connector, register
from src.connectors.sharepoint_connector import SharePointConnector  # noqa: F401
from src.connectors.web_url_connector import WebUrlConnector  # noqa: F401

__all__ = [
    "BaseConnector",
    "Document",
    "CONNECTOR_REGISTRY",
    "get_connector",
    "register",
    "ConfluenceConnector",
    "DatabaseConnector",
    "FileUploadConnector",
    "SharePointConnector",
    "WebUrlConnector",
]
