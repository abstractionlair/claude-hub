"""Connector interface for federated data access (R7).

Re-exports key types from base module and concrete implementations.
"""

from claude_hub.connectors.artifact_connector import ArtifactConnector
from claude_hub.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorItem,
    ConnectorResult,
    IndexReport,
)
from claude_hub.connectors.filesystem_connector import FilesystemConnector
from claude_hub.connectors.registry import ConnectorRegistry

__all__ = [
    "ArtifactConnector",
    "BaseConnector",
    "ConnectorError",
    "ConnectorItem",
    "ConnectorResult",
    "ConnectorRegistry",
    "FilesystemConnector",
    "IndexReport",
]
