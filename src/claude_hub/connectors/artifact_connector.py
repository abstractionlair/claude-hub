"""ArtifactConnector — wraps the existing artifact store as a BaseConnector (R7, Phase 5b).

Delegates to ``artifact_store.search_artifacts``, ``list_artifacts``, and
``get_artifact`` so the artifact store is queryable through the connector
interface.  Does **not** implement ``index()`` since artifacts embed on write.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import asyncpg

from claude_hub import artifact_store
from claude_hub.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ConnectorResult,
)


class ArtifactConnector(BaseConnector):
    """Connector that wraps the existing artifact store."""

    def __init__(self, name: str, config: dict[str, Any], pool: asyncpg.Pool) -> None:
        self._name = name
        self._config = config
        self._pool = pool
        self._connector_id: str = config.get("connector_id", str(_uuid.uuid4()))

    # ── Properties ───────────────────────────────────────────────────

    @property
    def connector_type(self) -> str:
        return "artifact_store"

    @property
    def name(self) -> str:
        return self._name

    @property
    def connector_id(self) -> str:
        return self._connector_id

    # ── Lifecycle ────────────────────────────────────────────────────

    async def validate(self) -> bool:
        """Check database connectivity."""
        await self._pool.fetchval("SELECT 1")
        return True

    # ── Query / List / Get ───────────────────────────────────────────

    async def query(
        self,
        query: str,
        filters: dict | None = None,
        limit: int = 10,
    ) -> list[ConnectorResult]:
        """Semantic search over artifacts.

        Delegates to ``artifact_store.search_artifacts``.
        """
        filters = filters or {}
        # Forward all supported filters to search_artifacts
        search_kwargs: dict = {
            "query": query,
            "artifact_type": filters.get("artifact_type"),
            "tags": filters.get("tags"),
            "limit": limit,
        }
        if "date_from" in filters:
            search_kwargs["date_from"] = filters["date_from"]
        if "date_to" in filters:
            search_kwargs["date_to"] = filters["date_to"]
        if "include_archived" in filters:
            search_kwargs["include_archived"] = filters["include_archived"]
        if "confidence" in filters:
            search_kwargs["confidence"] = filters["confidence"]
        results = await artifact_store.search_artifacts(
            self._pool,
            **search_kwargs,
        )
        return [
            ConnectorResult(
                content=r.get("content_preview") or "",
                source=f"artifact:{r['artifact_id']}",
                score=r.get("score", 0.0),
                metadata={
                    "artifact_id": r["artifact_id"],
                    "artifact_type": r.get("artifact_type"),
                    "tags": r.get("tags", []),
                    "created_at": r.get("created_at"),
                    "confidence": r.get("confidence"),
                    "utility_score": r.get("utility_score"),
                },
                connector_name=self._name,
            )
            for r in results
        ]

    async def list(
        self,
        path: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConnectorItem]:
        """List artifacts with pagination.

        Delegates to ``artifact_store.list_artifacts``.
        """
        response = await artifact_store.list_artifacts(
            self._pool,
            limit=limit,
            offset=offset,
        )
        return [
            ConnectorItem(
                id=r["artifact_id"],
                title=r.get("artifact_type", "artifact"),
                content=r.get("content_preview") or "",
                path=f"artifact:{r['artifact_id']}",
                metadata={
                    "artifact_type": r.get("artifact_type"),
                    "tags": r.get("tags", []),
                    "created_at": r.get("created_at"),
                    "archived": r.get("archived", False),
                },
            )
            for r in response.get("results", [])
        ]

    async def get(self, item_id: str) -> ConnectorItem:
        """Get a single artifact by ID.

        Delegates to ``artifact_store.get_artifact``.

        Raises:
            KeyError: If artifact not found.
        """
        result = await artifact_store.get_artifact(self._pool, artifact_id=item_id)
        if result is None:
            raise KeyError(f"Artifact '{item_id}' not found")
        return ConnectorItem(
            id=result["id"],
            title=result.get("artifact_type", "artifact"),
            content=result.get("content", ""),
            path=f"artifact:{result['id']}",
            metadata={
                "artifact_type": result.get("artifact_type"),
                "tags": result.get("tags", []),
                "source_ref": result.get("source_ref"),
                "created_at": result.get("created_at"),
                "confidence": result.get("confidence"),
                "utility_score": result.get("utility_score"),
                "archived": result.get("archived", False),
            },
        )
