"""Tests for the window-file continuity ingestion bridge."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.continuity import _serialize_frontmatter


# --- Fixtures ---


@pytest.fixture(autouse=True)
def set_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set CLAUDE_PROJECT_DIR to tmp_path for all tests."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CURRENT_ROLE", raising=False)
    (tmp_path / "thoughts" / "windows" / "claude-code").mkdir(parents=True)
    return tmp_path


def _make_window(directory: Path, filename: str, session_id: str = "test-session",
                 body: str = "Test content.\n", extra_metadata: dict | None = None) -> Path:
    """Create a window file with standard frontmatter.

    Args:
        extra_metadata: Additional frontmatter fields to include (e.g. role, projects, workstream).
    """
    path = directory / filename
    metadata = {
        "parent": None,
        "children": [],
        "session_id": session_id,
        "harness": "claude-code",
        "finalized": "false",
        "created": "2026-03-07T10:00:00Z",
        "updated": "2026-03-07T10:00:00Z",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    path.write_text(_serialize_frontmatter(metadata) + body)
    return path


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg pool."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()))
    return pool


# --- ingest_window ---


class TestIngestWindow:
    @pytest.mark.asyncio
    async def test_ingest_creates_artifact(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Ingest a window file — calls store_artifact with correct params."""
        from claude_hub.continuity_ingest import ingest_window

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        window = _make_window(directory, "2026-03-07T10-00-00Z.md", body="Session about MCP auth.\n")

        fake_result = {"artifact_id": "abc-123", "version": 1, "embedding_status": "pending"}
        with patch("claude_hub.continuity_ingest.store_artifact", new_callable=AsyncMock, return_value=fake_result) as mock_store:
            result = await ingest_window(mock_pool, window)

        assert result["action"] == "created"
        assert result["artifact_id"] == "abc-123"
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args
        assert call_kwargs[1]["artifact_type"] == "window"
        assert call_kwargs[1]["source_ref"] == "thoughts/windows/claude-code/2026-03-07T10-00-00Z.md"
        assert "claude-code" in call_kwargs[1]["tags"]
        assert call_kwargs[1]["metadata"]["session_id"] == "test-session"

    @pytest.mark.asyncio
    async def test_ingest_preserves_workstream_component_tags(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Workstream, component, and service frontmatter become prefixed tags."""
        from claude_hub.continuity_ingest import ingest_window

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        window = _make_window(
            directory, "2026-03-07T10-00-00Z.md",
            body="Working on infrastructure.\n",
            extra_metadata={
                "role": "workbench",
                "projects": ["claude-hub", "prediction-markets"],
                "workstream": "development",
                "component": "codebase",
                "service": "mcp-server",
            },
        )

        fake_result = {"artifact_id": "abc-123", "version": 1, "embedding_status": "pending"}
        with patch("claude_hub.continuity_ingest.store_artifact", new_callable=AsyncMock, return_value=fake_result) as mock_store:
            result = await ingest_window(mock_pool, window)

        assert result["action"] == "created"
        call_kwargs = mock_store.call_args[1]

        # Tags should include prefixed workstream, component, service
        assert "workstream:development" in call_kwargs["tags"]
        assert "component:codebase" in call_kwargs["tags"]
        assert "service:mcp-server" in call_kwargs["tags"]

        # Metadata should include role and projects
        assert call_kwargs["metadata"]["role"] == "workbench"
        assert call_kwargs["metadata"]["projects"] == ["claude-hub", "prediction-markets"]

    @pytest.mark.asyncio
    async def test_ingest_skips_empty_workstream_component(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Empty workstream/component values should not produce tags."""
        from claude_hub.continuity_ingest import ingest_window

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        window = _make_window(
            directory, "2026-03-07T10-00-00Z.md",
            body="Session without workstream.\n",
            extra_metadata={
                "workstream": "",
                "component": "",
            },
        )

        fake_result = {"artifact_id": "abc-123", "version": 1, "embedding_status": "pending"}
        with patch("claude_hub.continuity_ingest.store_artifact", new_callable=AsyncMock, return_value=fake_result) as mock_store:
            result = await ingest_window(mock_pool, window)

        assert result["action"] == "created"
        tags = mock_store.call_args[1]["tags"]
        # No workstream: or component: tags for empty values
        assert not any(t.startswith("workstream:") for t in tags)
        assert not any(t.startswith("component:") for t in tags)

    @pytest.mark.asyncio
    async def test_ingest_nonexistent_file(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Returns error for missing files."""
        from claude_hub.continuity_ingest import ingest_window

        result = await ingest_window(mock_pool, tmp_path / "nonexistent.md")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_ingest_empty_file(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Returns error for empty files."""
        from claude_hub.continuity_ingest import ingest_window

        empty = tmp_path / "thoughts" / "windows" / "claude-code" / "empty.md"
        empty.write_text("")

        result = await ingest_window(mock_pool, empty)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_ingest_skips_unchanged(self, tmp_path: Path) -> None:
        """Skips re-ingestion when content hash matches."""
        from claude_hub.continuity_ingest import ingest_window
        from claude_hub.artifact_store import compute_content_hash
        from claude_hub.continuity import _parse_frontmatter

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        window = _make_window(directory, "2026-03-07T10-00-00Z.md")
        raw = window.read_text()
        # Hash the body (what ingest_window stores), not the full file
        _, body = _parse_frontmatter(raw)
        content = body.strip()

        # Mock pool that returns existing artifact with same hash
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": "existing-id",
            "content_hash": compute_content_hash(content),
            "version": 1,
        })
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(),
        ))

        result = await ingest_window(pool, window)
        assert result["action"] == "skipped"
        assert result["artifact_id"] == "existing-id"

    @pytest.mark.asyncio
    async def test_ingest_updates_on_content_change(self, tmp_path: Path) -> None:
        """Updates artifact when content has changed."""
        from claude_hub.continuity_ingest import ingest_window

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        window = _make_window(directory, "2026-03-07T10-00-00Z.md", body="Updated content.\n")

        # Mock pool that returns existing artifact with different hash
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": "existing-id",
            "content_hash": "different-hash",
            "version": 1,
        })
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(),
        ))

        fake_result = {"artifact_id": "existing-id", "version": 2, "embedding_status": "pending"}
        with patch("claude_hub.continuity_ingest.update_artifact", new_callable=AsyncMock, return_value=fake_result):
            result = await ingest_window(pool, window)

        assert result["action"] == "updated"
        assert result["version"] == 2


# --- ingest_all_windows ---


class TestIngestAllWindows:
    @pytest.mark.asyncio
    async def test_ingest_all(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Ingests all window files in directory."""
        from claude_hub.continuity_ingest import ingest_all_windows

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        _make_window(directory, "2026-03-07T10-00-00Z.md", session_id="s1")
        _make_window(directory, "2026-03-07T11-00-00Z.md", session_id="s2")

        fake_result = {"artifact_id": "id", "version": 1, "embedding_status": "pending"}
        with patch("claude_hub.continuity_ingest.store_artifact", new_callable=AsyncMock, return_value=fake_result):
            result = await ingest_all_windows(mock_pool, harness="claude-code")

        assert result["created"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_ingest_all_empty_dir(self, tmp_path: Path, mock_pool: MagicMock) -> None:
        """Returns zeroes for empty directory."""
        from claude_hub.continuity_ingest import ingest_all_windows

        result = await ingest_all_windows(mock_pool, harness="nonexistent")
        assert result["created"] == 0
        assert result["skipped"] == 0


# --- search_windows ---


class TestSearchWindows:
    @pytest.mark.asyncio
    async def test_search(self, mock_pool: MagicMock) -> None:
        """Delegates to search_artifacts with correct type filter."""
        from claude_hub.continuity_ingest import search_windows

        fake_results = [
            {"artifact_id": "id1", "content_preview": "MCP auth...", "score": 0.87, "created_at": "2026-03-07"},
        ]
        with patch("claude_hub.continuity_ingest.search_artifacts", new_callable=AsyncMock, return_value=fake_results) as mock_search:
            results = await search_windows(mock_pool, "MCP authentication", limit=3)

        assert len(results) == 1
        mock_search.assert_called_once_with(mock_pool, query="MCP authentication", artifact_type="window", limit=3)

    @pytest.mark.asyncio
    async def test_search_empty(self, mock_pool: MagicMock) -> None:
        """Returns empty list when no matches."""
        from claude_hub.continuity_ingest import search_windows

        with patch("claude_hub.continuity_ingest.search_artifacts", new_callable=AsyncMock, return_value=[]):
            results = await search_windows(mock_pool, "nonexistent topic")

        assert results == []


# --- get_semantic_context ---


class TestGetSemanticContext:
    @pytest.mark.asyncio
    async def test_formats_context(self, mock_pool: MagicMock) -> None:
        """Formats search results as brief context string."""
        from claude_hub.continuity_ingest import get_semantic_context

        fake_results = [
            {"artifact_id": "id1", "content_preview": "Discussed MCP auth flow", "score": 0.87, "created_at": "2026-03-07T10:00:00Z"},
            {"artifact_id": "id2", "content_preview": "Set up OAuth tokens", "score": 0.72, "created_at": "2026-02-15T14:00:00Z"},
        ]
        with patch("claude_hub.continuity_ingest.search_windows", new_callable=AsyncMock, return_value=fake_results):
            output = await get_semantic_context(mock_pool, "authentication")

        assert "Related past sessions" in output
        assert "[0.87]" in output
        assert "MCP auth flow" in output
        assert "2026-02-15" in output

    @pytest.mark.asyncio
    async def test_empty_context(self, mock_pool: MagicMock) -> None:
        """Returns empty string when no results."""
        from claude_hub.continuity_ingest import get_semantic_context

        with patch("claude_hub.continuity_ingest.search_windows", new_callable=AsyncMock, return_value=[]):
            output = await get_semantic_context(mock_pool, "nothing relevant")

        assert output == ""
