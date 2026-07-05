"""Filesystem connector for indexing and searching local files (R7).

Walks a directory tree, indexes file content with SHA-256 dedup,
generates embeddings for semantic search, and serves results via
the standard connector interface.
"""

import hashlib
import logging
import os
from pathlib import Path

import asyncpg

from claude_hub.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorItem,
    ConnectorResult,
    IndexReport,
)
from claude_hub.embedding import generate_embedding, generate_query_embedding

logger = logging.getLogger(__name__)


class FilesystemConnector(BaseConnector):
    """Connector that indexes and searches local filesystem directories.

    Config schema::

        {
            "root_path": str,          # Absolute path to root directory
            "extensions": [".md"],     # File extensions to index (default [".md"])
            "recursive": true          # Walk subdirectories (default True)
        }
    """

    def __init__(self, name: str, config: dict, pool: asyncpg.Pool):
        self._name = name
        self._config = config
        self._pool = pool
        self._connector_id: str | None = config.get("connector_id")
        self._root_path = Path(config["root_path"]).resolve()
        self._extensions: list[str] = config.get("extensions", [".md"])
        self._recursive: bool = config.get("recursive", True)

    def _validate_path(self, path: str) -> Path:
        """Resolve a caller-supplied path and verify it stays under root_path.

        Raises:
            ConnectorError: If the resolved path escapes the root directory.
        """
        resolved = (self._root_path / path).resolve()
        if not resolved.is_relative_to(self._root_path):
            raise ConnectorError(
                f"Path escapes root directory: {path}",
                retriable=False,
            )
        return resolved

    @property
    def connector_type(self) -> str:
        return "filesystem"

    @property
    def name(self) -> str:
        return self._name

    @property
    def connector_id(self) -> str | None:
        return self._connector_id

    @connector_id.setter
    def connector_id(self, value: str) -> None:
        self._connector_id = value

    async def validate(self) -> bool:
        """Validate that root_path exists and is a directory."""
        if not self._root_path.exists():
            raise ConnectorError(
                f"Root path does not exist: {self._root_path}",
                retriable=False,
            )
        if not self._root_path.is_dir():
            raise ConnectorError(
                f"Root path is not a directory: {self._root_path}",
                retriable=False,
            )
        return True

    def _walk_files(self, scan_root: Path) -> list[Path]:
        """Collect files matching configured extensions under scan_root."""
        files: list[Path] = []
        if self._recursive:
            for dirpath, _dirnames, filenames in os.walk(scan_root):
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    if fpath.suffix in self._extensions:
                        files.append(fpath)
        else:
            for fpath in scan_root.iterdir():
                if fpath.is_file() and fpath.suffix in self._extensions:
                    files.append(fpath)
        return files

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        """SHA-256 hex digest of UTF-8 encoded content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_title(content: str, filename: str) -> str:
        """Extract title from first markdown heading or fall back to filename."""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return filename

    async def index(self, path: str | None = None) -> IndexReport:
        """Walk directory, upsert entries with content-hash dedup, generate embeddings."""
        if self._connector_id is None:
            raise ConnectorError(
                "connector_id must be set before indexing (register connector first)",
                retriable=False,
            )

        scan_root = self._validate_path(path) if path else self._root_path
        files = self._walk_files(scan_root)

        report = IndexReport()
        new_or_changed: list[tuple[str, str]] = []  # (source_path, content)

        async with self._pool.acquire() as conn:
            for fpath in files:
                report.items_scanned += 1

                # Validate each file resolves within root (symlink escape prevention)
                resolved = fpath.resolve()
                if not resolved.is_relative_to(self._root_path):
                    report.errors.append(f"Skipping {fpath}: resolves outside root")
                    continue

                source_path = str(fpath.relative_to(self._root_path))

                try:
                    content = resolved.read_text(encoding="utf-8")
                except Exception as exc:
                    report.errors.append(f"Error reading {source_path}: {exc}")
                    continue

                content_hash = self._compute_content_hash(content)
                title = self._extract_title(content, fpath.name)
                content_preview = content[:500]

                # Check existing entry
                existing = await conn.fetchrow(
                    """
                    SELECT id, content_hash
                    FROM connector_index
                    WHERE connector_id = $1::uuid AND source_path = $2
                    """,
                    self._connector_id,
                    source_path,
                )

                if existing is not None:
                    if existing["content_hash"] == content_hash:
                        report.items_skipped += 1
                        continue
                    # Content changed — update
                    await conn.execute(
                        """
                        UPDATE connector_index
                        SET content_hash = $1,
                            content_preview = $2,
                            title = $3,
                            embedding_status = 'pending',
                            indexed_at = NOW()
                        WHERE connector_id = $4::uuid AND source_path = $5
                        """,
                        content_hash,
                        content_preview,
                        title,
                        self._connector_id,
                        source_path,
                    )
                    report.items_indexed += 1
                    new_or_changed.append((source_path, content))
                else:
                    # New entry
                    await conn.execute(
                        """
                        INSERT INTO connector_index
                            (connector_id, source_path, content_hash, title, content_preview)
                        VALUES ($1::uuid, $2, $3, $4, $5)
                        """,
                        self._connector_id,
                        source_path,
                        content_hash,
                        title,
                        content_preview,
                    )
                    report.items_indexed += 1
                    new_or_changed.append((source_path, content))

        # Remove stale index entries for files that no longer exist on disk.
        # Only run stale cleanup on full-directory indexing (path=None).
        # Scoped indexing (path="subdir") only scans a subset, so entries
        # outside that scope would incorrectly appear stale and get deleted.
        if path is None:
            seen_paths = {
                str(fpath.relative_to(self._root_path)) for fpath in files
            }
            async with self._pool.acquire() as conn:
                indexed_rows = await conn.fetch(
                    """
                    SELECT source_path
                    FROM connector_index
                    WHERE connector_id = $1::uuid
                    """,
                    self._connector_id,
                )
                stale_paths = [
                    row["source_path"]
                    for row in indexed_rows
                    if row["source_path"] not in seen_paths
                ]
                if stale_paths:
                    await conn.execute(
                        """
                        DELETE FROM connector_index
                        WHERE connector_id = $1::uuid
                          AND source_path = ANY($2::text[])
                        """,
                        self._connector_id,
                        stale_paths,
                    )
                    report.items_deleted = len(stale_paths)

        # Generate embeddings for new/changed entries
        for source_path, content in new_or_changed:
            try:
                embedding = await generate_embedding(content)
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE connector_index
                        SET embedding = $1,
                            embedding_status = 'complete'
                        WHERE connector_id = $2::uuid AND source_path = $3
                        """,
                        embedding,
                        self._connector_id,
                        source_path,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to embed %s: %s", source_path, exc
                )
                report.errors.append(f"Embedding failed for {source_path}: {exc}")
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE connector_index
                        SET embedding_status = 'failed'
                        WHERE connector_id = $1::uuid AND source_path = $2
                        """,
                        self._connector_id,
                        source_path,
                    )

        return report

    async def query(
        self, query: str, filters: dict | None = None, limit: int = 10
    ) -> list[ConnectorResult]:
        """Semantic search over indexed files using vector similarity."""
        if self._connector_id is None:
            return []

        query_vec = await generate_query_embedding(query)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT source_path, content_preview, title,
                       1 - (embedding <=> $1::vector) AS score
                FROM connector_index
                WHERE connector_id = $2::uuid
                  AND embedding_status = 'complete'
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                query_vec,
                self._connector_id,
                limit,
            )

        return [
            ConnectorResult(
                content=row["content_preview"] or "",
                source=row["source_path"],
                score=float(row["score"]),
                metadata={"title": row["title"]},
                connector_name=self._name,
            )
            for row in rows
        ]

    async def list(
        self, path: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[ConnectorItem]:
        """List indexed items, ordered by most recently indexed."""
        if self._connector_id is None:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, source_path, title, content_preview, indexed_at
                FROM connector_index
                WHERE connector_id = $1::uuid
                ORDER BY indexed_at DESC
                LIMIT $2 OFFSET $3
                """,
                self._connector_id,
                limit,
                offset,
            )

        return [
            ConnectorItem(
                id=row["source_path"],
                title=row["title"] or row["source_path"],
                content=row["content_preview"] or "",
                path=row["source_path"],
                metadata={"indexed_at": row["indexed_at"].isoformat()},
            )
            for row in rows
        ]

    async def get(self, item_id: str) -> ConnectorItem:
        """Get a specific file by its source_path relative to root_path.

        Reads the actual file content from disk.
        """
        try:
            file_path = self._validate_path(item_id)
        except ConnectorError:
            raise KeyError(f"Path escapes root directory: {item_id}")
        if not file_path.exists():
            raise KeyError(f"File not found: {item_id}")
        if not file_path.is_file():
            raise KeyError(f"Not a file: {item_id}")

        content = file_path.read_text(encoding="utf-8")
        title = self._extract_title(content, file_path.name)

        return ConnectorItem(
            id=item_id,
            title=title,
            content=content,
            path=item_id,
            metadata={"full_path": str(file_path)},
        )
