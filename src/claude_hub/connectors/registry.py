"""ConnectorRegistry — in-memory registry with federated query (R7, Phase 5b).

Manages named connectors and provides a single ``federated_query`` entry point
that fans out to all (or a subset of) registered connectors in parallel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from claude_hub.connectors.base import ConnectorResult

if TYPE_CHECKING:
    from claude_hub.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Manages connector instances and provides federated query."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    # ── CRUD ─────────────────────────────────────────────────────────

    def register(self, connector: BaseConnector) -> None:
        """Register a connector.

        Args:
            connector: Connector instance to register.

        Raises:
            ValueError: If a connector with the same name is already registered.
        """
        name = connector.name
        if name in self._connectors:
            raise ValueError(f"Connector '{name}' is already registered")
        self._connectors[name] = connector

    def unregister(self, name: str) -> None:
        """Remove a connector by name.

        Raises:
            KeyError: If no connector with that name exists.
        """
        if name not in self._connectors:
            raise KeyError(f"Connector '{name}' is not registered")
        del self._connectors[name]

    def get(self, name: str) -> BaseConnector:
        """Return a connector by name.

        Raises:
            KeyError: If not found.
        """
        try:
            return self._connectors[name]
        except KeyError:
            raise KeyError(f"Connector '{name}' is not registered")

    @property
    def active_connectors(self) -> list[BaseConnector]:
        """Return all registered connectors."""
        return list(self._connectors.values())

    # ── Federated query ──────────────────────────────────────────────

    async def federated_query(
        self,
        query: str,
        connector_names: list[str] | None = None,
        filters: dict | None = None,
        limit: int = 10,
        timeout: float = 30.0,
    ) -> list[ConnectorResult]:
        """Query multiple connectors in parallel and merge results.

        Args:
            query: Natural-language search query.
            connector_names: Subset of connectors to query.  If ``None``,
                all registered connectors are queried.
            filters: Connector-specific filters passed through to each
                connector's ``query()`` method.
            limit: Maximum total results after merging.
            timeout: Per-connector timeout in seconds (default 30s).

        Returns:
            Merged results sorted by score (descending), truncated to *limit*.

        Note:
            Each connector independently generates query embeddings.
            This is redundant for indexed connectors but negligible at
            current scale (2 connectors). If connector count grows
            significantly, consider generating the embedding once and
            passing it through.
        """
        if connector_names is not None:
            targets: list[BaseConnector] = []
            for name in connector_names:
                connector = self._connectors.get(name)
                if connector is None:
                    logger.warning(
                        "federated_query: skipping unknown connector '%s'", name
                    )
                    continue
                targets.append(connector)
        else:
            targets = list(self._connectors.values())

        if not targets:
            return []

        tasks = [
            asyncio.wait_for(
                connector.query(query, filters=filters, limit=limit),
                timeout=timeout,
            )
            for connector in targets
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[ConnectorResult] = []
        for connector, outcome in zip(targets, outcomes):
            if isinstance(outcome, BaseException):
                if isinstance(outcome, asyncio.TimeoutError):
                    logger.error(
                        "federated_query: connector '%s' timed out after %.1fs",
                        connector.name,
                        timeout,
                    )
                else:
                    logger.error(
                        "federated_query: connector '%s' raised %s: %s",
                        connector.name,
                        type(outcome).__name__,
                        outcome,
                    )
                continue
            merged.extend(outcome)

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:limit]
