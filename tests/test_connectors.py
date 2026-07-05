"""Tests for the connector interface (Phase 5a + 5b + 5c + 5d)."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorItem,
    ConnectorResult,
    IndexReport,
)
from claude_hub.connectors.registry import ConnectorRegistry


class TestConnectorError:
    """Test ConnectorError exception."""

    def test_has_retriable_attribute_default_false(self):
        err = ConnectorError("something failed")
        assert err.retriable is False
        assert str(err) == "something failed"

    def test_retriable_true(self):
        err = ConnectorError("timeout", retriable=True)
        assert err.retriable is True
        assert str(err) == "timeout"

    def test_is_exception(self):
        with pytest.raises(ConnectorError):
            raise ConnectorError("boom")


class TestConnectorResult:
    """Test ConnectorResult dataclass."""

    def test_construction_minimal(self):
        result = ConnectorResult(content="hello", source="/path", score=0.9)
        assert result.content == "hello"
        assert result.source == "/path"
        assert result.score == 0.9
        assert result.metadata == {}
        assert result.connector_name == ""

    def test_construction_full(self):
        result = ConnectorResult(
            content="world",
            source="/other",
            score=0.5,
            metadata={"key": "val"},
            connector_name="my-connector",
        )
        assert result.metadata == {"key": "val"}
        assert result.connector_name == "my-connector"


class TestConnectorItem:
    """Test ConnectorItem dataclass."""

    def test_construction_minimal(self):
        item = ConnectorItem(id="abc", title="Title", content="Body", path="/a/b")
        assert item.id == "abc"
        assert item.title == "Title"
        assert item.content == "Body"
        assert item.path == "/a/b"
        assert item.metadata == {}

    def test_construction_with_metadata(self):
        item = ConnectorItem(
            id="x", title="T", content="C", path="/p", metadata={"a": 1}
        )
        assert item.metadata == {"a": 1}


class TestIndexReport:
    """Test IndexReport dataclass."""

    def test_defaults(self):
        report = IndexReport()
        assert report.items_scanned == 0
        assert report.items_indexed == 0
        assert report.items_skipped == 0
        assert report.errors == []

    def test_construction(self):
        report = IndexReport(
            items_scanned=10, items_indexed=8, items_skipped=2, errors=["bad file"]
        )
        assert report.items_scanned == 10
        assert report.items_indexed == 8
        assert report.items_skipped == 2
        assert report.errors == ["bad file"]


class TestBaseConnector:
    """Test BaseConnector abstract class."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseConnector()  # type: ignore[abstract]

    def test_mock_subclass(self):
        """A concrete subclass can be instantiated and passes isinstance check."""

        class MockConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "test-mock"

            async def query(self, query, filters=None, limit=10):
                return [ConnectorResult(content="found", source="/x", score=1.0)]

            async def list(self, path=None, limit=50, offset=0):
                return [
                    ConnectorItem(id="1", title="Item", content="Body", path="/x")
                ]

            async def get(self, item_id):
                return ConnectorItem(
                    id=item_id, title="Item", content="Body", path="/x"
                )

        connector = MockConnector()
        assert isinstance(connector, BaseConnector)
        assert connector.connector_type == "mock"
        assert connector.name == "test-mock"

    @pytest.mark.asyncio
    async def test_mock_subclass_query(self):
        """Mock subclass can be called."""

        class MockConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "test-mock"

            async def query(self, query, filters=None, limit=10):
                return [
                    ConnectorResult(
                        content="result", source="/s", score=0.8, connector_name="test-mock"
                    )
                ]

            async def list(self, path=None, limit=50, offset=0):
                return []

            async def get(self, item_id):
                return ConnectorItem(
                    id=item_id, title="T", content="C", path="/p"
                )

        connector = MockConnector()
        results = await connector.query("test query")
        assert len(results) == 1
        assert results[0].content == "result"
        assert results[0].connector_name == "test-mock"

    @pytest.mark.asyncio
    async def test_validate_default_returns_true(self):
        """Default validate() returns True."""

        class MockConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "m"

            async def query(self, query, filters=None, limit=10):
                return []

            async def list(self, path=None, limit=50, offset=0):
                return []

            async def get(self, item_id):
                return ConnectorItem(id=item_id, title="T", content="C", path="/p")

        connector = MockConnector()
        assert await connector.validate() is True

    @pytest.mark.asyncio
    async def test_index_default_raises(self):
        """Default index() raises NotImplementedError."""

        class MockConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "m"

            async def query(self, query, filters=None, limit=10):
                return []

            async def list(self, path=None, limit=50, offset=0):
                return []

            async def get(self, item_id):
                return ConnectorItem(id=item_id, title="T", content="C", path="/p")

        connector = MockConnector()
        with pytest.raises(NotImplementedError, match="mock connector does not support indexing"):
            await connector.index()

    @pytest.mark.asyncio
    async def test_write_default_raises(self):
        """Default write() raises NotImplementedError."""

        class MockConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "m"

            async def query(self, query, filters=None, limit=10):
                return []

            async def list(self, path=None, limit=50, offset=0):
                return []

            async def get(self, item_id):
                return ConnectorItem(id=item_id, title="T", content="C", path="/p")

        connector = MockConnector()
        with pytest.raises(NotImplementedError, match="mock connector does not support writes"):
            await connector.write("id", "content")


class TestConnectorPackageImports:
    """Test that the connectors package re-exports types correctly."""

    def test_imports_from_package(self):
        from claude_hub.connectors import (  # noqa: F401
            BaseConnector,
            ConnectorError,
            ConnectorItem,
            ConnectorResult,
            IndexReport,
        )

        # Verify they're the same objects
        from claude_hub.connectors.base import (
            BaseConnector as BC,
            ConnectorError as CE,
            ConnectorItem as CI,
            ConnectorResult as CR,
            IndexReport as IR,
        )

        assert BaseConnector is BC
        assert ConnectorError is CE
        assert ConnectorItem is CI
        assert ConnectorResult is CR
        assert IndexReport is IR

    def test_imports_registry_and_artifact_connector(self):
        from claude_hub.connectors import (  # noqa: F401
            ArtifactConnector,
            ConnectorRegistry,
        )
        from claude_hub.connectors.artifact_connector import (
            ArtifactConnector as AC,
        )
        from claude_hub.connectors.registry import (
            ConnectorRegistry as CR,
        )

        assert ArtifactConnector is AC
        assert ConnectorRegistry is CR


# ── Helpers ──────────────────────────────────────────────────────────


def _make_mock_connector(
    name: str, results: list[ConnectorResult] | None = None
) -> BaseConnector:
    """Create a mock BaseConnector with given name and query results."""

    class _Mock(BaseConnector):
        @property
        def connector_type(self) -> str:
            return "mock"

        @property
        def name(self) -> str:
            return name

        async def query(self, query, filters=None, limit=10):
            return results or []

        async def list(self, path=None, limit=50, offset=0):
            return []

        async def get(self, item_id):
            return ConnectorItem(id=item_id, title="T", content="C", path="/p")

    return _Mock()


def _make_failing_connector(name: str, error: Exception) -> BaseConnector:
    """Create a mock connector whose query() always raises."""

    class _Failing(BaseConnector):
        @property
        def connector_type(self) -> str:
            return "mock"

        @property
        def name(self) -> str:
            return name

        async def query(self, query, filters=None, limit=10):
            raise error

        async def list(self, path=None, limit=50, offset=0):
            return []

        async def get(self, item_id):
            return ConnectorItem(id=item_id, title="T", content="C", path="/p")

    return _Failing()


# ── ConnectorRegistry tests ─────────────────────────────────────────


class TestConnectorRegistry:
    """Test ConnectorRegistry CRUD and federated query."""

    def test_register_and_get(self):
        reg = ConnectorRegistry()
        c = _make_mock_connector("alpha")
        reg.register(c)
        assert reg.get("alpha") is c

    def test_register_duplicate_rejected(self):
        reg = ConnectorRegistry()
        reg.register(_make_mock_connector("alpha"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_make_mock_connector("alpha"))

    def test_unregister(self):
        reg = ConnectorRegistry()
        reg.register(_make_mock_connector("alpha"))
        reg.unregister("alpha")
        with pytest.raises(KeyError):
            reg.get("alpha")

    def test_unregister_missing(self):
        reg = ConnectorRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.unregister("nope")

    def test_active_connectors(self):
        reg = ConnectorRegistry()
        a = _make_mock_connector("a")
        b = _make_mock_connector("b")
        reg.register(a)
        reg.register(b)
        active = reg.active_connectors
        assert len(active) == 2
        assert set(c.name for c in active) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_federated_query_merges_results(self):
        reg = ConnectorRegistry()
        reg.register(
            _make_mock_connector(
                "c1",
                [
                    ConnectorResult(
                        content="A", source="/a", score=0.9, connector_name="c1"
                    ),
                    ConnectorResult(
                        content="C", source="/c", score=0.5, connector_name="c1"
                    ),
                ],
            )
        )
        reg.register(
            _make_mock_connector(
                "c2",
                [
                    ConnectorResult(
                        content="B", source="/b", score=0.7, connector_name="c2"
                    ),
                ],
            )
        )

        results = await reg.federated_query("test", limit=10)
        assert len(results) == 3
        # Sorted by score descending
        assert results[0].score == 0.9
        assert results[0].content == "A"
        assert results[1].score == 0.7
        assert results[1].content == "B"
        assert results[2].score == 0.5
        assert results[2].content == "C"

    @pytest.mark.asyncio
    async def test_federated_query_connector_failure_isolated(self):
        reg = ConnectorRegistry()
        reg.register(
            _make_mock_connector(
                "good",
                [ConnectorResult(content="ok", source="/ok", score=0.8)],
            )
        )
        reg.register(
            _make_failing_connector("bad", RuntimeError("kaboom"))
        )

        results = await reg.federated_query("test")
        assert len(results) == 1
        assert results[0].content == "ok"

    @pytest.mark.asyncio
    async def test_federated_query_subset(self):
        reg = ConnectorRegistry()
        reg.register(
            _make_mock_connector(
                "a",
                [ConnectorResult(content="from-a", source="/a", score=0.9)],
            )
        )
        reg.register(
            _make_mock_connector(
                "b",
                [ConnectorResult(content="from-b", source="/b", score=0.8)],
            )
        )

        results = await reg.federated_query("test", connector_names=["a"])
        assert len(results) == 1
        assert results[0].content == "from-a"

    @pytest.mark.asyncio
    async def test_federated_query_limit(self):
        reg = ConnectorRegistry()
        reg.register(
            _make_mock_connector(
                "big",
                [
                    ConnectorResult(content=f"r{i}", source=f"/{i}", score=1.0 - i * 0.1)
                    for i in range(5)
                ],
            )
        )
        results = await reg.federated_query("test", limit=3)
        assert len(results) == 3
        # Top 3 by score
        assert results[0].score == 1.0
        assert results[1].score == 0.9
        assert results[2].score == 0.8

    @pytest.mark.asyncio
    async def test_federated_query_timeout_isolates_slow_connector(self):
        """A connector that times out should not block others."""
        import asyncio

        class _SlowConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return "mock"

            @property
            def name(self) -> str:
                return "slow"

            async def query(self, query, filters=None, limit=10):
                await asyncio.sleep(10)  # Much longer than timeout
                return []

            async def list(self, path=None, limit=50, offset=0):
                return []

            async def get(self, item_id):
                return ConnectorItem(id=item_id, title="T", content="C", path="/p")

        reg = ConnectorRegistry()
        reg.register(_SlowConnector())
        reg.register(
            _make_mock_connector(
                "fast",
                [ConnectorResult(content="ok", source="/ok", score=0.9)],
            )
        )

        # With a short timeout, slow connector times out but fast one succeeds
        results = await reg.federated_query("test", timeout=0.1)
        assert len(results) == 1
        assert results[0].content == "ok"

    @pytest.mark.asyncio
    async def test_federated_query_empty_registry(self):
        """federated_query with no connectors returns empty list."""
        reg = ConnectorRegistry()
        results = await reg.federated_query("test")
        assert results == []


# ── ArtifactConnector tests ─────────────────────────────────────────


class TestArtifactConnector:
    """Test ArtifactConnector delegation to artifact_store."""

    def _make_connector(self, pool=None):
        from claude_hub.connectors.artifact_connector import ArtifactConnector

        pool = pool or MagicMock()
        return ArtifactConnector(name="test-artifacts", config={}, pool=pool)

    def test_connector_type(self):
        c = self._make_connector()
        assert c.connector_type == "artifact_store"

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_query_delegates(self, mock_store):
        mock_store.search_artifacts = AsyncMock(
            return_value=[
                {
                    "artifact_id": "abc-123",
                    "content_preview": "Hello world",
                    "artifact_type": "note",
                    "tags": ["test"],
                    "score": 0.85,
                    "created_at": "2026-01-01T00:00:00",
                    "confidence": "HIGH",
                    "utility_score": 0.7,
                }
            ]
        )

        pool = MagicMock()
        c = self._make_connector(pool)
        results = await c.query("test query", limit=5)

        mock_store.search_artifacts.assert_awaited_once_with(
            pool,
            query="test query",
            artifact_type=None,
            tags=None,
            limit=5,
        )
        assert len(results) == 1
        r = results[0]
        assert r.content == "Hello world"
        assert r.source == "artifact:abc-123"
        assert r.score == 0.85
        assert r.connector_name == "test-artifacts"
        assert r.metadata["artifact_id"] == "abc-123"
        assert r.metadata["artifact_type"] == "note"

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_list_delegates(self, mock_store):
        mock_store.list_artifacts = AsyncMock(
            return_value={
                "results": [
                    {
                        "artifact_id": "id-1",
                        "artifact_type": "note",
                        "tags": [],
                        "content_preview": "Preview",
                        "created_at": "2026-01-01T00:00:00",
                        "archived": False,
                    }
                ],
                "total_count": 1,
            }
        )

        pool = MagicMock()
        c = self._make_connector(pool)
        items = await c.list(limit=10, offset=0)

        mock_store.list_artifacts.assert_awaited_once_with(
            pool, limit=10, offset=0
        )
        assert len(items) == 1
        assert items[0].id == "id-1"
        assert items[0].content == "Preview"
        assert items[0].path == "artifact:id-1"

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_get_delegates(self, mock_store):
        mock_store.get_artifact = AsyncMock(
            return_value={
                "id": "id-1",
                "content": "Full content here",
                "artifact_type": "note",
                "tags": ["a"],
                "source_ref": "test.py",
                "created_at": "2026-01-01T00:00:00",
                "confidence": "MEDIUM",
                "utility_score": 0.5,
                "archived": False,
            }
        )

        pool = MagicMock()
        c = self._make_connector(pool)
        item = await c.get("id-1")

        mock_store.get_artifact.assert_awaited_once_with(pool, artifact_id="id-1")
        assert item.id == "id-1"
        assert item.content == "Full content here"
        assert item.title == "note"
        assert item.path == "artifact:id-1"
        assert item.metadata["tags"] == ["a"]

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_get_not_found_raises_key_error(self, mock_store):
        mock_store.get_artifact = AsyncMock(return_value=None)

        c = self._make_connector()
        with pytest.raises(KeyError, match="not found"):
            await c.get("missing-id")

    @pytest.mark.asyncio
    async def test_validate_checks_pool(self):
        pool = MagicMock()
        pool.fetchval = AsyncMock(return_value=1)

        c = self._make_connector(pool)
        result = await c.validate()

        assert result is True
        pool.fetchval.assert_awaited_once_with("SELECT 1")

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_query_forwards_all_filters(self, mock_store):
        """query() should forward date_from, date_to, include_archived, confidence."""
        mock_store.search_artifacts = AsyncMock(return_value=[])

        pool = MagicMock()
        c = self._make_connector(pool)
        await c.query(
            "test query",
            filters={
                "artifact_type": "note",
                "tags": ["tag1"],
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
                "include_archived": True,
                "confidence": "HIGH",
            },
            limit=5,
        )

        mock_store.search_artifacts.assert_awaited_once_with(
            pool,
            query="test query",
            artifact_type="note",
            tags=["tag1"],
            limit=5,
            date_from="2026-01-01",
            date_to="2026-12-31",
            include_archived=True,
            confidence="HIGH",
        )

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_query_omits_absent_filters(self, mock_store):
        """query() should not pass filter keys that aren't in the filters dict."""
        mock_store.search_artifacts = AsyncMock(return_value=[])

        pool = MagicMock()
        c = self._make_connector(pool)
        await c.query("test", filters={"artifact_type": "note"}, limit=5)

        mock_store.search_artifacts.assert_awaited_once_with(
            pool,
            query="test",
            artifact_type="note",
            tags=None,
            limit=5,
        )


# ── FilesystemConnector tests (Phase 5c) ─────────────────────────────


class TestFilesystemConnector:
    """Test FilesystemConnector."""

    FAKE_CONNECTOR_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    FAKE_VECTOR = [0.1] * 768

    def _make_connector(self, root_path, pool=None, extensions=None, recursive=True):
        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        config = {
            "root_path": str(root_path),
            "recursive": recursive,
            "connector_id": self.FAKE_CONNECTOR_ID,
        }
        if extensions is not None:
            config["extensions"] = extensions
        pool = pool or MagicMock()
        return FilesystemConnector(name="test-fs", config=config, pool=pool)

    def _mock_pool(self):
        """Build a mock asyncpg pool with async context manager on acquire."""
        pool = MagicMock()
        conn = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = ctx
        return pool, conn

    def test_connector_type(self):
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            assert c.connector_type == "filesystem"

    def test_name(self):
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            assert c.name == "test-fs"

    @pytest.mark.asyncio
    async def test_validate_good_path(self):
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            result = await c.validate()
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_bad_path(self):
        c = self._make_connector("/nonexistent/path/that/does/not/exist")
        with pytest.raises(ConnectorError, match="does not exist"):
            await c.validate()

    @pytest.mark.asyncio
    async def test_validate_not_directory(self):
        with tempfile.NamedTemporaryFile() as tf:
            c = self._make_connector(tf.name)
            with pytest.raises(ConnectorError, match="not a directory"):
                await c.validate()

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_walks_directory(self, mock_embed):
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # all files are new

        with tempfile.TemporaryDirectory() as td:
            # Create 3 markdown files
            for i in range(3):
                with open(os.path.join(td, f"doc{i}.md"), "w") as f:
                    f.write(f"# Document {i}\n\nContent of document {i}.")

            c = self._make_connector(td, pool=pool)
            report = await c.index()

        assert report.items_scanned == 3
        assert report.items_indexed == 3
        assert report.items_skipped == 0
        assert report.errors == []
        assert mock_embed.call_count == 3

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_dedup_unchanged(self, mock_embed):
        """Indexing unchanged files should skip them."""
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()

        with tempfile.TemporaryDirectory() as td:
            content = "# Test\n\nSome content."
            filepath = os.path.join(td, "test.md")
            with open(filepath, "w") as f:
                f.write(content)

            import hashlib
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # First index: file is new
            conn.fetchrow.return_value = None
            c = self._make_connector(td, pool=pool)
            report1 = await c.index()
            assert report1.items_indexed == 1
            assert report1.items_skipped == 0

            # Second index: file unchanged (hash matches)
            conn.fetchrow.return_value = {
                "id": "some-uuid",
                "content_hash": content_hash,
            }
            report2 = await c.index()
            assert report2.items_scanned == 1
            assert report2.items_indexed == 0
            assert report2.items_skipped == 1

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_detects_changes(self, mock_embed):
        """Re-indexing after modification should detect the change."""
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()

        with tempfile.TemporaryDirectory() as td:
            filepath = os.path.join(td, "test.md")
            with open(filepath, "w") as f:
                f.write("# Original\n\nOriginal content.")

            # File exists in index but with old hash
            conn.fetchrow.return_value = {
                "id": "some-uuid",
                "content_hash": "old-hash-that-wont-match",
            }

            c = self._make_connector(td, pool=pool)
            report = await c.index()

            assert report.items_scanned == 1
            assert report.items_indexed == 1
            assert report.items_skipped == 0

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_respects_extensions(self, mock_embed):
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # all new

        with tempfile.TemporaryDirectory() as td:
            # Create .md and .txt files
            with open(os.path.join(td, "include.md"), "w") as f:
                f.write("# Included")
            with open(os.path.join(td, "exclude.txt"), "w") as f:
                f.write("Excluded")
            with open(os.path.join(td, "also_excluded.py"), "w") as f:
                f.write("# Also excluded")

            c = self._make_connector(td, pool=pool, extensions=[".md"])
            report = await c.index()

        assert report.items_scanned == 1
        assert report.items_indexed == 1

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_query_embedding")
    async def test_query_uses_vector_search(self, mock_query_embed):
        mock_query_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()

        # Mock the fetch result for vector search
        mock_row = {
            "source_path": "docs/test.md",
            "content_preview": "Test content",
            "title": "Test",
            "score": 0.85,
        }
        conn.fetch.return_value = [mock_row]

        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td, pool=pool)
            results = await c.query("search term", limit=5)

        mock_query_embed.assert_awaited_once_with("search term")
        assert len(results) == 1
        assert results[0].content == "Test content"
        assert results[0].source == "docs/test.md"
        assert results[0].score == 0.85
        assert results[0].metadata["title"] == "Test"
        assert results[0].connector_name == "test-fs"

        # Verify the SQL was called with the right parameters
        conn.fetch.assert_awaited_once()
        call_args = conn.fetch.call_args
        sql = call_args[0][0]
        assert "connector_index" in sql
        assert "embedding_status = 'complete'" in sql
        assert "vector" in sql.lower() or "<=>" in sql

    @pytest.mark.asyncio
    async def test_list_from_index(self):
        pool, conn = self._mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch.return_value = [
            {
                "id": "uuid-1",
                "source_path": "doc1.md",
                "title": "Document 1",
                "content_preview": "Preview 1",
                "indexed_at": now,
            },
            {
                "id": "uuid-2",
                "source_path": "doc2.md",
                "title": "Document 2",
                "content_preview": "Preview 2",
                "indexed_at": now,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td, pool=pool)
            items = await c.list(limit=10)

        assert len(items) == 2
        # list() should use source_path as id (not DB UUID) so get(item.id) works
        assert items[0].id == "doc1.md"
        assert items[0].title == "Document 1"
        assert items[0].content == "Preview 1"
        assert items[0].path == "doc1.md"
        assert items[1].id == "doc2.md"

    @pytest.mark.asyncio
    async def test_get_reads_file(self):
        with tempfile.TemporaryDirectory() as td:
            content = "# My Document\n\nFull content here."
            filepath = os.path.join(td, "test.md")
            with open(filepath, "w") as f:
                f.write(content)

            c = self._make_connector(td)
            item = await c.get("test.md")

        assert item.id == "test.md"
        assert item.title == "My Document"
        assert item.content == content
        assert item.path == "test.md"

    @pytest.mark.asyncio
    async def test_get_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            with pytest.raises(KeyError, match="not found"):
                await c.get("nonexistent.md")

    @pytest.mark.asyncio
    async def test_connector_id_property(self):
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            assert c.connector_id == self.FAKE_CONNECTOR_ID
            c.connector_id = "new-id"
            assert c.connector_id == "new-id"

    @pytest.mark.asyncio
    async def test_index_without_connector_id_raises(self):
        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        with tempfile.TemporaryDirectory() as td:
            config = {"root_path": str(td)}
            c = FilesystemConnector(name="test", config=config, pool=MagicMock())
            with pytest.raises(ConnectorError, match="connector_id must be set"):
                await c.index()

    def test_extract_title_heading(self):
        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        title = FilesystemConnector._extract_title("# Hello World\nBody", "file.md")
        assert title == "Hello World"

    def test_extract_title_fallback(self):
        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        title = FilesystemConnector._extract_title("No heading here", "fallback.md")
        assert title == "fallback.md"

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_embedding_failure_recorded(self, mock_embed):
        """If embedding fails, error is recorded but indexing continues."""
        mock_embed.side_effect = RuntimeError("API error")
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # file is new

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "test.md"), "w") as f:
                f.write("# Test\n\nContent.")

            c = self._make_connector(td, pool=pool)
            report = await c.index()

        assert report.items_scanned == 1
        assert report.items_indexed == 1
        assert len(report.errors) == 1
        assert "Embedding failed" in report.errors[0]

    # ── Path traversal security tests ──────────────────────────────

    @pytest.mark.asyncio
    async def test_get_rejects_path_traversal(self):
        """get() must reject paths that escape root_path via ../."""
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            with pytest.raises(KeyError, match="Path escapes root"):
                await c.get("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_get_rejects_absolute_path_traversal(self):
        """get() must reject traversal attempts with complex relative paths."""
        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td)
            with pytest.raises(KeyError, match="Path escapes root"):
                await c.get("subdir/../../../etc/shadow")

    @pytest.mark.asyncio
    async def test_get_rejects_symlink_escape(self):
        """get() must reject symlinks that point outside root_path."""
        with tempfile.TemporaryDirectory() as td:
            # Create a symlink inside root that points outside
            link_path = os.path.join(td, "escape.md")
            os.symlink("/etc/hostname", link_path)

            c = self._make_connector(td)
            # The resolved path of the symlink is outside root_path
            with pytest.raises(KeyError, match="Path escapes root"):
                await c.get("escape.md")

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_rejects_path_traversal(self, mock_embed):
        """index(path=...) must reject paths that escape root_path."""
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()

        with tempfile.TemporaryDirectory() as td:
            c = self._make_connector(td, pool=pool)
            with pytest.raises(ConnectorError, match="Path escapes root"):
                await c.index(path="../../etc")

    # ── list/get round-trip test ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_get_roundtrip(self):
        """list() returns items whose id can be passed to get() successfully."""
        pool, conn = self._mock_pool()

        now = datetime.now(timezone.utc)
        conn.fetch.return_value = [
            {
                "id": "some-uuid-ignored",
                "source_path": "test.md",
                "title": "Test Doc",
                "content_preview": "Preview",
                "indexed_at": now,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            # Create the actual file so get() can read it
            content = "# Test Doc\n\nFull content here."
            with open(os.path.join(td, "test.md"), "w") as f:
                f.write(content)

            c = self._make_connector(td, pool=pool)
            items = await c.list(limit=10)
            assert len(items) == 1

            # Round-trip: get() with the id from list()
            item = await c.get(items[0].id)
            assert item.id == "test.md"
            assert item.content == content
            assert item.title == "Test Doc"

    # ── Stale index entry cleanup test ─────────────────────────────

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_index_removes_stale_entries(self, mock_embed):
        """index() should remove entries for files that no longer exist on disk."""
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # all files are new

        with tempfile.TemporaryDirectory() as td:
            # Create one file
            with open(os.path.join(td, "keep.md"), "w") as f:
                f.write("# Keep\n\nThis stays.")

            # Mock: DB has an entry for a file that's been deleted
            conn.fetch.return_value = [
                {"source_path": "keep.md"},
                {"source_path": "deleted.md"},  # No longer on disk
            ]

            c = self._make_connector(td, pool=pool)
            report = await c.index()

        assert report.items_deleted == 1
        # Verify DELETE was called with the stale path
        delete_calls = [
            call for call in conn.execute.call_args_list
            if "DELETE" in str(call)
        ]
        assert len(delete_calls) == 1

    # ── Scoped indexing preserves entries outside scope ─────────────

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_scoped_index_preserves_entries_outside_scope(self, mock_embed):
        """index(path='subdir') must NOT delete entries outside 'subdir'.

        Regression test: previously, stale cleanup ran unconditionally,
        so a scoped index would delete everything outside the scan scope.
        """
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # all files are new

        with tempfile.TemporaryDirectory() as td:
            # Create files in a subdirectory
            subdir = os.path.join(td, "subdir")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "inner.md"), "w") as f:
                f.write("# Inner\n\nInside subdir.")

            # Also create a file at root level (outside subdir)
            with open(os.path.join(td, "root.md"), "w") as f:
                f.write("# Root\n\nAt root level.")

            # Mock: DB already has an entry for root.md (indexed previously)
            conn.fetch.return_value = [
                {"source_path": "root.md"},
                {"source_path": "subdir/inner.md"},
            ]

            c = self._make_connector(td, pool=pool)
            # Scoped index: only scan subdir
            report = await c.index(path="subdir")

        # The file inside subdir should be indexed
        assert report.items_scanned == 1
        assert report.items_indexed == 1
        # Crucially: no entries should be deleted (stale cleanup skipped)
        assert report.items_deleted == 0
        # Verify DELETE was NOT called
        delete_calls = [
            call for call in conn.execute.call_args_list
            if "DELETE" in str(call)
        ]
        assert len(delete_calls) == 0

    # ── IndexReport.items_deleted default ──────────────────────────

    def test_index_report_has_items_deleted(self):
        """IndexReport includes items_deleted field defaulting to 0."""
        report = IndexReport()
        assert report.items_deleted == 0


class TestFilesystemConnectorPackageImport:
    """Test that FilesystemConnector is re-exported from the package."""

    def test_import_from_package(self):
        from claude_hub.connectors import FilesystemConnector  # noqa: F401
        from claude_hub.connectors.filesystem_connector import (
            FilesystemConnector as FC,
        )

        assert FilesystemConnector is FC


# ── MCP Endpoint tests (Phase 5d) ───────────────────────────────────


def _mock_pool_for_endpoints():
    """Build a mock asyncpg pool with async context manager on acquire."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = ctx
    return pool, conn


class TestMCPEndpoints:
    """Test connector MCP tool endpoints (Phase 5d)."""

    @pytest.mark.asyncio
    async def test_connector_register_success(self):
        """connector_register with valid type inserts to DB and registers."""
        from claude_hub.server import tool_connector_register
        from claude_hub.connector_models import ConnectorRegisterRequest

        pool, conn = _mock_pool_for_endpoints()

        fake_id = str(uuid.uuid4())
        conn.fetchval.return_value = None  # no duplicate
        conn.fetchrow.return_value = {"id": fake_id, "status": "active"}

        # The pool itself needs fetchval for ArtifactConnector.validate()
        pool.fetchval = AsyncMock(return_value=1)

        registry = ConnectorRegistry()

        with patch("claude_hub.server.require_pg_pool", return_value=pool), \
             patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = ConnectorRegisterRequest(
                name="test-artifacts",
                connector_type="artifact_store",
                config={},
            )
            response = await tool_connector_register(request, client="test-client")

        assert response.connector_id == fake_id
        assert response.name == "test-artifacts"
        assert response.connector_type == "artifact_store"
        assert response.status == "active"

        # Verify connector was registered in the registry
        instance = registry.get("test-artifacts")
        assert instance.name == "test-artifacts"

    @pytest.mark.asyncio
    async def test_connector_register_unknown_type(self):
        """connector_register with unknown type returns 400."""
        from claude_hub.server import tool_connector_register
        from claude_hub.connector_models import ConnectorRegisterRequest
        from fastapi import HTTPException

        pool, conn = _mock_pool_for_endpoints()
        registry = ConnectorRegistry()

        with patch("claude_hub.server.require_pg_pool", return_value=pool), \
             patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = ConnectorRegisterRequest(
                name="bad-connector",
                connector_type="unknown_type",
                config={},
            )
            with pytest.raises(HTTPException) as exc_info:
                await tool_connector_register(request, client="test-client")

        assert exc_info.value.status_code == 400
        assert "Unknown connector type" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_connector_register_duplicate_name(self):
        """connector_register with duplicate name returns 409."""
        from claude_hub.server import tool_connector_register
        from claude_hub.connector_models import ConnectorRegisterRequest
        from fastapi import HTTPException

        pool, conn = _mock_pool_for_endpoints()
        conn.fetchval.return_value = str(uuid.uuid4())  # existing connector found
        registry = ConnectorRegistry()

        with patch("claude_hub.server.require_pg_pool", return_value=pool), \
             patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = ConnectorRegisterRequest(
                name="duplicate-name",
                connector_type="artifact_store",
                config={},
            )
            with pytest.raises(HTTPException) as exc_info:
                await tool_connector_register(request, client="test-client")

        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_connector_index_success(self):
        """connector_index calls index() and updates status."""
        from claude_hub.server import tool_connector_index
        from claude_hub.connector_models import ConnectorIndexRequest

        pool, conn = _mock_pool_for_endpoints()
        fake_id = str(uuid.uuid4())
        conn.fetchrow.return_value = {"id": fake_id, "name": "test-fs"}

        # Create a mock connector with index() support
        mock_connector = MagicMock()
        mock_connector.name = "test-fs"
        mock_report = IndexReport(items_scanned=10, items_indexed=8, items_skipped=2)
        mock_connector.index = AsyncMock(return_value=mock_report)

        registry = ConnectorRegistry()
        registry._connectors["test-fs"] = mock_connector

        with patch("claude_hub.server.require_pg_pool", return_value=pool), \
             patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = ConnectorIndexRequest(connector_id=fake_id)
            response = await tool_connector_index(request, client="test-client")

        assert response.connector_id == fake_id
        assert response.items_scanned == 10
        assert response.items_indexed == 8
        assert response.items_skipped == 2
        assert response.errors == []

        # Verify index() was called
        mock_connector.index.assert_awaited_once_with(path=None)

        # Verify status was updated to 'indexing' then 'active'
        execute_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("indexing" in c for c in execute_calls)
        assert any("active" in c for c in execute_calls)

    @pytest.mark.asyncio
    async def test_connector_index_not_found(self):
        """connector_index with unknown ID returns 404."""
        from claude_hub.server import tool_connector_index
        from claude_hub.connector_models import ConnectorIndexRequest
        from fastapi import HTTPException

        pool, conn = _mock_pool_for_endpoints()
        conn.fetchrow.return_value = None  # not found

        registry = ConnectorRegistry()

        with patch("claude_hub.server.require_pg_pool", return_value=pool), \
             patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = ConnectorIndexRequest(connector_id=str(uuid.uuid4()))
            with pytest.raises(HTTPException) as exc_info:
                await tool_connector_index(request, client="test-client")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_query_federated_success(self):
        """query_federated returns merged results from registry."""
        from claude_hub.server import tool_query_federated
        from claude_hub.connector_models import QueryFederatedRequest

        registry = ConnectorRegistry()
        registry.register(
            _make_mock_connector(
                "c1",
                [
                    ConnectorResult(
                        content="Result A", source="/a", score=0.9, connector_name="c1"
                    ),
                ],
            )
        )
        registry.register(
            _make_mock_connector(
                "c2",
                [
                    ConnectorResult(
                        content="Result B", source="/b", score=0.7, connector_name="c2"
                    ),
                ],
            )
        )

        with patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = QueryFederatedRequest(query="test query", limit=10)
            response = await tool_query_federated(request, client="test-client")

        assert response.total == 2
        assert len(response.results) == 2
        # Sorted by score descending
        assert response.results[0].content == "Result A"
        assert response.results[0].score == 0.9
        assert response.results[0].connector_name == "c1"
        assert response.results[1].content == "Result B"
        assert response.results[1].score == 0.7
        assert response.results[1].connector_name == "c2"

    @pytest.mark.asyncio
    async def test_query_federated_empty(self):
        """query_federated with no connectors returns empty results."""
        from claude_hub.server import tool_query_federated
        from claude_hub.connector_models import QueryFederatedRequest

        registry = ConnectorRegistry()

        with patch("claude_hub.server.require_connector_registry", return_value=registry):
            request = QueryFederatedRequest(query="test query")
            response = await tool_query_federated(request, client="test-client")

        assert response.total == 0
        assert response.results == []


# ── Integration tests (Phase 5e) ─────────────────────────────────────


class TestIntegration:
    """End-to-end acceptance tests for the connector system (Phase 5e).

    These exercise the full code paths with mocked pools (no real Postgres),
    verifying the four acceptance criteria from the spec.
    """

    def _mock_pool(self):
        """Build a mock asyncpg pool with async context manager on acquire."""
        pool = MagicMock()
        conn = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = ctx
        return pool, conn

    FAKE_CONNECTOR_ID = "11111111-2222-3333-4444-555555555555"
    FAKE_VECTOR = [0.1] * 768

    # ── Acceptance Test 1: Artifact store queryable through connector ──

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    async def test_acceptance_artifact_store_queryable_through_connector(
        self, mock_store
    ):
        """Artifact store is queryable through the connector interface and
        returns the same results as a direct artifact_store.search_artifacts call,
        mapped to ConnectorResult objects.
        """
        from claude_hub.connectors.artifact_connector import ArtifactConnector

        # What artifact_store.search_artifacts would return directly
        raw_artifacts = [
            {
                "artifact_id": "art-001",
                "content_preview": "Machine learning notes",
                "artifact_type": "note",
                "tags": ["ml", "research"],
                "score": 0.92,
                "created_at": "2026-03-01T00:00:00",
                "confidence": "HIGH",
                "utility_score": 0.8,
            },
            {
                "artifact_id": "art-002",
                "content_preview": "Python best practices",
                "artifact_type": "learning",
                "tags": ["python"],
                "score": 0.78,
                "created_at": "2026-02-15T00:00:00",
                "confidence": "MEDIUM",
                "utility_score": 0.6,
            },
        ]
        mock_store.search_artifacts = AsyncMock(return_value=raw_artifacts)

        pool = MagicMock()
        connector = ArtifactConnector(
            name="artifacts",
            config={"connector_id": self.FAKE_CONNECTOR_ID},
            pool=pool,
        )

        results = await connector.query("machine learning", limit=10)

        # Verify search_artifacts was called with the right query
        mock_store.search_artifacts.assert_awaited_once()
        call_kwargs = mock_store.search_artifacts.call_args
        assert call_kwargs[1]["query"] == "machine learning"

        # Verify results are properly mapped ConnectorResults
        assert len(results) == 2
        assert all(isinstance(r, ConnectorResult) for r in results)

        # First result preserves content, source, score, and metadata
        assert results[0].content == "Machine learning notes"
        assert results[0].source == "artifact:art-001"
        assert results[0].score == 0.92
        assert results[0].connector_name == "artifacts"
        assert results[0].metadata["artifact_id"] == "art-001"
        assert results[0].metadata["artifact_type"] == "note"
        assert results[0].metadata["tags"] == ["ml", "research"]

        # Second result also correctly mapped
        assert results[1].content == "Python best practices"
        assert results[1].source == "artifact:art-002"
        assert results[1].score == 0.78
        assert results[1].metadata["artifact_type"] == "learning"

    # ── Acceptance Test 2: Filesystem connector indexes directory ──────

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_embedding")
    async def test_acceptance_filesystem_connector_indexes_directory(
        self, mock_embed
    ):
        """Filesystem connector indexes a directory of .md files,
        scanning all files, inserting rows into the index, and generating
        embeddings for each.
        """
        mock_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()
        conn.fetchrow.return_value = None  # all files are new (not in index yet)
        # No stale entries in DB
        conn.fetch.return_value = []

        # Track all SQL INSERT calls
        insert_calls = []
        original_execute = conn.execute

        async def capture_execute(sql, *args, **kwargs):
            if "INSERT" in sql:
                insert_calls.append((sql, args))
            return await original_execute(sql, *args, **kwargs)

        conn.execute = AsyncMock(side_effect=capture_execute)

        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        with tempfile.TemporaryDirectory() as td:
            # Create 3 .md files with distinct content
            files = {
                "notes.md": "# Study Notes\n\nImportant concepts.",
                "design.md": "# Design Doc\n\nArchitecture decisions.",
                "todo.md": "# TODO\n\nAction items for the week.",
            }
            for fname, content in files.items():
                with open(os.path.join(td, fname), "w") as f:
                    f.write(content)

            config = {
                "root_path": str(td),
                "connector_id": self.FAKE_CONNECTOR_ID,
                "extensions": [".md"],
            }
            connector = FilesystemConnector(name="test-docs", config=config, pool=pool)
            report = await connector.index()

        # Verify IndexReport
        assert report.items_scanned == 3
        assert report.items_indexed == 3
        assert report.items_skipped == 0
        assert report.errors == []

        # Verify 3 INSERT calls were made to connector_index
        assert len(insert_calls) == 3

        # Verify embeddings were generated for all 3 files
        assert mock_embed.call_count == 3

    # ── Acceptance Test 3: Semantic search across filesystem connector ─

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.filesystem_connector.generate_query_embedding")
    async def test_acceptance_filesystem_semantic_search(self, mock_query_embed):
        """Semantic search across a filesystem connector returns results
        with scores and correct source paths based on vector similarity.
        """
        mock_query_embed.return_value = self.FAKE_VECTOR
        pool, conn = self._mock_pool()

        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        # Mock vector search results as they'd come from Postgres
        conn.fetch.return_value = [
            {
                "source_path": "research/deep-learning.md",
                "content_preview": "Neural network architectures and training strategies",
                "title": "Deep Learning Notes",
                "score": 0.95,
            },
            {
                "source_path": "research/transformers.md",
                "content_preview": "Attention mechanisms and transformer models",
                "title": "Transformers",
                "score": 0.87,
            },
            {
                "source_path": "misc/python-tips.md",
                "content_preview": "Useful Python patterns",
                "title": "Python Tips",
                "score": 0.42,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            config = {
                "root_path": str(td),
                "connector_id": self.FAKE_CONNECTOR_ID,
            }
            connector = FilesystemConnector(
                name="research-docs", config=config, pool=pool
            )
            results = await connector.query("neural networks", limit=10)

        # Verify query embedding was generated
        mock_query_embed.assert_awaited_once_with("neural networks")

        # Verify results
        assert len(results) == 3
        assert all(isinstance(r, ConnectorResult) for r in results)

        # Results have correct source paths
        assert results[0].source == "research/deep-learning.md"
        assert results[1].source == "research/transformers.md"
        assert results[2].source == "misc/python-tips.md"

        # Results have correct scores
        assert results[0].score == 0.95
        assert results[1].score == 0.87
        assert results[2].score == 0.42

        # Results have correct connector_name
        assert all(r.connector_name == "research-docs" for r in results)

        # Results have metadata with title
        assert results[0].metadata["title"] == "Deep Learning Notes"
        assert results[1].metadata["title"] == "Transformers"

        # Verify the SQL query targeted the right connector_id and status
        call_args = conn.fetch.call_args
        sql = call_args[0][0]
        assert "connector_index" in sql
        assert "embedding_status = 'complete'" in sql

    # ── Acceptance Test 4: Federated query merges results from both ────

    @pytest.mark.asyncio
    @patch("claude_hub.connectors.artifact_connector.artifact_store")
    @patch("claude_hub.connectors.filesystem_connector.generate_query_embedding")
    async def test_acceptance_federated_query_merges_both_connectors(
        self, mock_query_embed, mock_store
    ):
        """Federated query across an ArtifactConnector and a FilesystemConnector
        merges results from both, sorts by score descending, and tags each
        result with the correct connector_name.
        """
        from claude_hub.connectors.artifact_connector import ArtifactConnector
        from claude_hub.connectors.filesystem_connector import FilesystemConnector

        # ── Set up ArtifactConnector ──
        mock_store.search_artifacts = AsyncMock(
            return_value=[
                {
                    "artifact_id": "art-99",
                    "content_preview": "Artifact about machine learning",
                    "artifact_type": "learning",
                    "tags": ["ml"],
                    "score": 0.88,
                    "created_at": "2026-03-01T00:00:00",
                    "confidence": "HIGH",
                    "utility_score": 0.7,
                },
            ]
        )

        artifact_pool = MagicMock()
        artifact_connector = ArtifactConnector(
            name="my-artifacts", config={}, pool=artifact_pool
        )

        # ── Set up FilesystemConnector ──
        mock_query_embed.return_value = self.FAKE_VECTOR
        fs_pool, fs_conn = self._mock_pool()
        fs_conn.fetch.return_value = [
            {
                "source_path": "docs/guide.md",
                "content_preview": "ML guide with examples",
                "title": "ML Guide",
                "score": 0.93,
            },
            {
                "source_path": "docs/faq.md",
                "content_preview": "Frequently asked questions",
                "title": "FAQ",
                "score": 0.65,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            fs_config = {
                "root_path": str(td),
                "connector_id": self.FAKE_CONNECTOR_ID,
            }
            fs_connector = FilesystemConnector(
                name="my-files", config=fs_config, pool=fs_pool
            )

            # ── Register both in a registry ──
            registry = ConnectorRegistry()
            registry.register(artifact_connector)
            registry.register(fs_connector)

            # ── Federated query ──
            results = await registry.federated_query(
                "machine learning", limit=10
            )

        # Verify results contain items from BOTH connectors
        connector_names = {r.connector_name for r in results}
        assert "my-artifacts" in connector_names
        assert "my-files" in connector_names

        # Verify total count: 1 from artifact + 2 from filesystem = 3
        assert len(results) == 3

        # Verify sorted by score descending
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

        # Verify exact ordering: 0.93 (fs), 0.88 (artifact), 0.65 (fs)
        assert results[0].score == 0.93
        assert results[0].connector_name == "my-files"
        assert results[0].source == "docs/guide.md"

        assert results[1].score == 0.88
        assert results[1].connector_name == "my-artifacts"
        assert results[1].source == "artifact:art-99"

        assert results[2].score == 0.65
        assert results[2].connector_name == "my-files"
        assert results[2].source == "docs/faq.md"

        # Verify each result has the correct connector_name
        for r in results:
            assert r.connector_name in ("my-artifacts", "my-files")
