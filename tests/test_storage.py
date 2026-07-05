"""Tests for StorageManager and GitHubClient."""

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_hub.storage import StorageManager, StorageError, PathTraversalError
from claude_hub.github_tools import GitHubClient, GitHubError


# ---------------------------------------------------------------------------
# StorageManager fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_storage(tmp_path):
    """Create a StorageManager with a temporary directory as root."""
    return StorageManager(storage_root=str(tmp_path))


@pytest.fixture
def populated_storage(tmp_storage):
    """StorageManager with some pre-populated files."""
    tmp_storage.write_file("notes/hello.md", "# Hello World\nSome content here.")
    tmp_storage.write_file("notes/todo.md", "# TODO\n- Buy milk\n- Fix bugs")
    tmp_storage.write_file("data/config.json", '{"key": "value"}')
    return tmp_storage


# ---------------------------------------------------------------------------
# StorageManager: read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_read_existing_file(self, tmp_storage):
        tmp_storage.write_file("test.txt", "hello world")
        content = tmp_storage.read_file("test.txt")
        assert content == "hello world"

    def test_read_nested_file(self, tmp_storage):
        tmp_storage.write_file("a/b/c.txt", "deep")
        content = tmp_storage.read_file("a/b/c.txt")
        assert content == "deep"

    def test_read_nonexistent_file(self, tmp_storage):
        with pytest.raises(StorageError, match="File not found"):
            tmp_storage.read_file("missing.txt")

    def test_read_directory_as_file(self, tmp_storage):
        tmp_storage.write_file("dir/file.txt", "content")
        with pytest.raises(StorageError, match="Not a file"):
            tmp_storage.read_file("dir")


# ---------------------------------------------------------------------------
# StorageManager: write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_write_new_file(self, tmp_storage):
        abs_path = tmp_storage.write_file("new.txt", "new content")
        assert Path(abs_path).exists()
        assert tmp_storage.read_file("new.txt") == "new content"

    def test_write_creates_parent_dirs(self, tmp_storage):
        abs_path = tmp_storage.write_file("a/b/c/d.txt", "nested")
        assert Path(abs_path).exists()
        assert tmp_storage.read_file("a/b/c/d.txt") == "nested"

    def test_write_overwrites_existing(self, tmp_storage):
        tmp_storage.write_file("overwrite.txt", "first")
        tmp_storage.write_file("overwrite.txt", "second")
        assert tmp_storage.read_file("overwrite.txt") == "second"

    def test_write_returns_absolute_path(self, tmp_storage):
        abs_path = tmp_storage.write_file("abs.txt", "content")
        assert os.path.isabs(abs_path)


# ---------------------------------------------------------------------------
# StorageManager: list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_root(self, populated_storage):
        entries = populated_storage.list_files()
        names = [e["name"] for e in entries]
        assert "data" in names
        assert "notes" in names

    def test_list_subdir(self, populated_storage):
        entries = populated_storage.list_files("notes")
        names = [e["name"] for e in entries]
        assert "hello.md" in names
        assert "todo.md" in names

    def test_list_recursive(self, populated_storage):
        entries = populated_storage.list_files("", recursive=True)
        names = [e["name"] for e in entries]
        # Should include nested paths
        assert any("hello.md" in n for n in names)
        assert any("config.json" in n for n in names)

    def test_list_entry_fields(self, populated_storage):
        entries = populated_storage.list_files("notes")
        for entry in entries:
            assert "name" in entry
            assert "type" in entry
            assert "size" in entry
            assert "modified" in entry
            assert entry["type"] in ("file", "dir")

    def test_list_nonexistent_dir(self, tmp_storage):
        with pytest.raises(StorageError, match="Directory not found"):
            tmp_storage.list_files("nonexistent")

    def test_list_file_as_dir(self, tmp_storage):
        tmp_storage.write_file("file.txt", "content")
        with pytest.raises(StorageError, match="Not a directory"):
            tmp_storage.list_files("file.txt")


# ---------------------------------------------------------------------------
# StorageManager: append_file
# ---------------------------------------------------------------------------


class TestAppendFile:
    def test_append_to_existing(self, tmp_storage):
        tmp_storage.write_file("log.txt", "line1\n")
        tmp_storage.append_file("log.txt", "line2\n")
        content = tmp_storage.read_file("log.txt")
        assert content == "line1\nline2\n"

    def test_append_creates_new_file(self, tmp_storage):
        abs_path = tmp_storage.append_file("new_log.txt", "first entry\n")
        assert Path(abs_path).exists()
        assert tmp_storage.read_file("new_log.txt") == "first entry\n"

    def test_append_creates_parent_dirs(self, tmp_storage):
        tmp_storage.append_file("logs/app/server.log", "started\n")
        assert tmp_storage.read_file("logs/app/server.log") == "started\n"


# ---------------------------------------------------------------------------
# StorageManager: search_files
# ---------------------------------------------------------------------------


class TestSearchFiles:
    def test_search_finds_match(self, populated_storage):
        results = populated_storage.search_files("Hello World")
        assert len(results) >= 1
        assert any("hello.md" in r["file"] for r in results)

    def test_search_returns_line_numbers(self, populated_storage):
        results = populated_storage.search_files("Buy milk")
        assert len(results) >= 1
        assert all(isinstance(r["line"], int) for r in results)
        assert all(r["line"] > 0 for r in results)

    def test_search_no_results(self, populated_storage):
        results = populated_storage.search_files("zzz_nonexistent_zzz")
        assert len(results) == 0

    def test_search_with_glob_pattern(self, populated_storage):
        results = populated_storage.search_files("key", glob_pattern="*.json")
        assert len(results) >= 1
        assert all("config.json" in r["file"] for r in results)

    def test_search_in_subdir(self, populated_storage):
        results = populated_storage.search_files("content", path="notes")
        assert len(results) >= 1

    def test_search_nonexistent_dir(self, tmp_storage):
        with pytest.raises(StorageError, match="Directory not found"):
            tmp_storage.search_files("query", path="nonexistent")


# ---------------------------------------------------------------------------
# StorageManager: Path Traversal Protection (CRITICAL)
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Test that path traversal attacks are blocked."""

    def test_dotdot_in_path(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.read_file("../etc/passwd")

    def test_dotdot_nested(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.read_file("a/../../etc/passwd")

    def test_dotdot_deep(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.read_file("a/b/c/../../../../../../../etc/passwd")

    def test_dotdot_write(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.write_file("../etc/evil.txt", "pwned")

    def test_dotdot_append(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.append_file("../etc/evil.txt", "pwned")

    def test_dotdot_list(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.list_files("../etc")

    def test_dotdot_search(self, tmp_storage):
        with pytest.raises(PathTraversalError):
            tmp_storage.search_files("root", path="../etc")

    def test_absolute_path_rejected(self, tmp_storage):
        """Absolute paths that resolve outside root are rejected."""
        with pytest.raises(PathTraversalError):
            tmp_storage.read_file("../../../etc/passwd")

    def test_legitimate_dotdot_rejected(self, tmp_storage):
        """Even paths that resolve inside root but contain .. are rejected."""
        # Create a/b/c.txt so a/../a/b/c.txt would resolve inside root
        tmp_storage.write_file("a/b/c.txt", "content")
        with pytest.raises(PathTraversalError):
            tmp_storage.read_file("a/../a/b/c.txt")


# ---------------------------------------------------------------------------
# StorageManager: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_path_list(self, tmp_storage):
        """Empty path should list root."""
        entries = tmp_storage.list_files("")
        assert isinstance(entries, list)

    def test_unicode_content(self, tmp_storage):
        """Unicode content should round-trip correctly."""
        content = "Hello \u4e16\u754c \U0001f600 \u00e9\u00e8\u00ea"
        tmp_storage.write_file("unicode.txt", content)
        assert tmp_storage.read_file("unicode.txt") == content

    def test_large_content(self, tmp_storage):
        """Large files should be handled."""
        content = "x" * 1_000_000  # 1MB
        tmp_storage.write_file("large.txt", content)
        assert len(tmp_storage.read_file("large.txt")) == 1_000_000

    def test_env_var_storage_root(self, tmp_path):
        """STORAGE_ROOT env var should be respected."""
        custom_root = str(tmp_path / "custom_storage")
        with patch.dict(os.environ, {"STORAGE_ROOT": custom_root}):
            mgr = StorageManager()
            assert mgr.storage_root == Path(custom_root).resolve()


# ---------------------------------------------------------------------------
# GitHubClient
# ---------------------------------------------------------------------------


class TestGitHubClient:
    def test_read_file_decodes_base64(self):
        """Test that base64 content is decoded correctly."""
        client = GitHubClient(pat="test-token")

        content = "Hello, GitHub!"
        encoded = base64.b64encode(content.encode()).decode()

        mock_response = {
            "type": "file",
            "content": encoded,
            "path": "README.md",
            "sha": "abc123def456",
            "size": len(content),
        }

        with patch.object(client, "_make_request", return_value=mock_response):
            result = client.read_file("owner", "repo", "README.md")

        assert result["content"] == content
        assert result["path"] == "README.md"
        assert result["sha"] == "abc123def456"
        assert result["size"] == len(content)

    def test_read_file_builds_correct_url(self):
        """Test that the correct GitHub API URL is constructed."""
        client = GitHubClient(pat="test-token")

        mock_response = {
            "type": "file",
            "content": base64.b64encode(b"content").decode(),
            "path": "src/main.py",
            "sha": "abc123",
            "size": 7,
        }

        with patch.object(client, "_make_request", return_value=mock_response) as mock_req:
            client.read_file("myowner", "myrepo", "src/main.py", ref="develop")

        mock_req.assert_called_once_with(
            "https://api.github.com/repos/myowner/myrepo/contents/src/main.py?ref=develop"
        )

    def test_read_file_not_a_file(self):
        """Test that non-file types raise an error."""
        client = GitHubClient(pat="test-token")

        mock_response = {
            "type": "dir",
            "content": "",
            "path": "src",
        }

        with patch.object(client, "_make_request", return_value=mock_response):
            with pytest.raises(GitHubError, match="not a file"):
                client.read_file("owner", "repo", "src")

    def test_read_file_default_ref(self):
        """Test that default ref is 'main'."""
        client = GitHubClient(pat="test-token")

        mock_response = {
            "type": "file",
            "content": base64.b64encode(b"x").decode(),
            "path": "file.txt",
            "sha": "abc",
            "size": 1,
        }

        with patch.object(client, "_make_request", return_value=mock_response) as mock_req:
            client.read_file("o", "r", "file.txt")

        url = mock_req.call_args[0][0]
        assert "ref=main" in url

    def test_env_var_pat(self):
        """Test that GITHUB_PAT env var is used."""
        with patch.dict(os.environ, {"GITHUB_PAT": "env-token"}):
            client = GitHubClient()
            assert client.pat == "env-token"

    def test_no_pat(self):
        """Test that missing PAT defaults to empty string."""
        with patch.dict(os.environ, {}, clear=True):
            client = GitHubClient()
            assert client.pat == ""


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


class TestWebhookSignature:
    def test_valid_signature(self):
        """Test that valid HMAC-SHA256 signatures pass verification."""
        import hashlib
        import hmac as hmac_mod

        from claude_hub.server import _verify_github_signature

        secret = "test-secret"
        payload = b'{"action": "push"}'
        sig = "sha256=" + hmac_mod.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()

        assert _verify_github_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        from claude_hub.server import _verify_github_signature

        assert _verify_github_signature(b"payload", "sha256=invalid", "secret") is False

    def test_wrong_secret(self):
        import hashlib
        import hmac as hmac_mod

        from claude_hub.server import _verify_github_signature

        payload = b"data"
        sig = "sha256=" + hmac_mod.new(
            b"secret1", payload, hashlib.sha256
        ).hexdigest()

        assert _verify_github_signature(payload, sig, "secret2") is False
