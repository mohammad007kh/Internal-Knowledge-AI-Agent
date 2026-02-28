"""Factory for instantiating connectors through the DI container."""

from __future__ import annotations

import logging
from typing import Any

from src.connectors.base import BaseConnector
from src.connectors.registry import get_connector
from src.models.enums import SourceType

logger = logging.getLogger(__name__)


class ConnectorFactory:
    """Thin wrapper around :func:`get_connector` that:

    - Centralises connector instantiation.
    - Logs *source_id* + *source_type* for observability **without** exposing
      the decrypted config (FR-020).
    - Provides a single mock target for unit tests.
    """

    def build(
        self,
        source_type: SourceType,
        source_id: str,
        decrypted_config: dict[str, Any],
    ) -> BaseConnector:
        """Instantiate and return a connector for the given *source_type*.

        Args:
            source_type: The :class:`~src.models.enums.SourceType` enum value.
            source_id: UUID string of the :class:`~src.models.source.Source`
                (used for logging only — never forwarded to the connector).
            decrypted_config: Plaintext config dict — **never** logged (FR-020).

        Returns:
            A concrete :class:`~src.connectors.base.BaseConnector` instance.

        Raises:
            ValueError: if *source_type* is not registered in
                :data:`~src.connectors.registry.CONNECTOR_REGISTRY`.
        """
        logger.info(
            "ConnectorFactory.build",
            extra={"source_id": source_id, "source_type": source_type.value},
        )
        return get_connector(source_type, decrypted_config)
