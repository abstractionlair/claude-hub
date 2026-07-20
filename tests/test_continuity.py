"""Tests for the window-file continuity system."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_hub.continuity import (
    _parse_frontmatter,
    _serialize_frontmatter,
    append_window,
    create_window,
    finalize_window,
    find_current_window,
    find_latest_window,
    link_child,
    load_window_chain,
)


@pytest.fixture(autouse=True)
def set_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set CLAUDE_PROJECT_DIR to tmp_path for all tests."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CURRENT_ROLE", raising=False)
    # Create the base directory structure
    (tmp_path / "thoughts" / "windows" / "claude-code").mkdir(parents=True)
    return tmp_path


# --- Frontmatter parsing/serialization ---


class TestFrontmatter:
    def test_parse_simple(self) -> None:
        text = '---\nparent: null\nchildren: []\nsession_id: "abc"\n---\nBody here.'
        meta, body = _parse_frontmatter(text)
        assert meta["parent"] is None
        assert meta["children"] == []
        assert meta["session_id"] == "abc"
        assert body == "Body here."

    def test_parse_with_children(self) -> None:
        text = '---\nchildren: ["a.md", "b.md"]\n---\nContent'
        meta, body = _parse_frontmatter(text)
        assert meta["children"] == ["a.md", "b.md"]

    def test_parse_no_frontmatter(self) -> None:
        text = "Just a regular file."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Just a regular file."

    def test_roundtrip(self) -> None:
        original: dict[str, object] = {
            "parent": None,
            "children": ["child1.md"],
            "session_id": "test-123",
        }
        serialized = _serialize_frontmatter(original)
        parsed, body = _parse_frontmatter(serialized)
        assert parsed["parent"] is None
        assert parsed["children"] == ["child1.md"]
        assert parsed["session_id"] == "test-123"
        assert body == ""


# --- create_window ---


class TestCreateWindow:
    def test_create_window(self, tmp_path: Path) -> None:
        """Creates file with correct frontmatter, .current pointer exists."""
        path = create_window("session-abc")

        assert path.exists()
        assert path.suffix == ".md"
        assert path.parent == tmp_path / "thoughts" / "windows" / "claude-code"

        # Check filename format: YYYY-MM-DDTHH-MM-SSZ.md
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.md$", path.name)

        # Check frontmatter
        text = path.read_text()
        meta, body = _parse_frontmatter(text)
        assert meta["session_id"] == "session-abc"
        assert meta["harness"] == "claude-code"
        assert meta["parent"] is None
        assert meta["children"] == []
        assert meta["created"] is not None
        assert meta["updated"] is not None

        # Check .current pointer
        pointer = path.parent / ".current-session-abc"
        assert pointer.exists()
        assert pointer.read_text().strip() == path.name

    def test_create_window_with_parent(self, tmp_path: Path) -> None:
        """Links parent, updates parent's children list."""
        parent_path = create_window("session-1")
        child_path = create_window("session-2", parent=parent_path.name)

        # Child's frontmatter should reference parent
        child_meta, _ = _parse_frontmatter(child_path.read_text())
        assert child_meta["parent"] == parent_path.name

        # Parent's children should include child
        parent_meta, _ = _parse_frontmatter(parent_path.read_text())
        assert child_path.name in parent_meta["children"]

    def test_same_second_collision_pointer_uses_suffixed_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "claude_hub.continuity._timestamp_filename",
            lambda: "2026-07-12T19-30-00Z.md",
        )

        first = create_window("session-first")
        second = create_window("session-second")

        assert first.name == "2026-07-12T19-30-00Z.md"
        assert second.name == "2026-07-12T19-30-00Z-1.md"
        assert (second.parent / ".current-session-second").read_text().strip() == second.name

    def test_create_window_custom_harness(self, tmp_path: Path) -> None:
        """Creates window in custom harness directory."""
        path = create_window("session-x", harness="gemini", projects=["example-project"])

        assert path.parent == tmp_path / "thoughts" / "windows" / "gemini"
        meta, _ = _parse_frontmatter(path.read_text())
        assert meta["harness"] == "gemini"
        assert meta["projects"] == ["example-project"]


class TestAppendWindow:
    def test_append_updates_body_and_timestamp(self) -> None:
        path = create_window("session-append")
        before, _ = _parse_frontmatter(path.read_text())

        assert append_window(path, "## Turn update\n\nCompleted the test.")

        after, body = _parse_frontmatter(path.read_text())
        assert "Completed the test." in body
        assert after["updated"] >= before["updated"]

    def test_append_refuses_finalized_window(self) -> None:
        path = create_window("session-finalized")
        assert finalize_window(path)

        assert not append_window(path, "late content")
        assert "late content" not in path.read_text()


# --- link_child ---


class TestLinkChild:
    def test_link_child_same_harness(self, tmp_path: Path) -> None:
        """Links child within same harness directory."""
        parent = create_window("s1")
        child = create_window("s2")

        link_child(parent, child)

        meta, _ = _parse_frontmatter(parent.read_text())
        assert child.name in meta["children"]

    def test_link_child_idempotent(self, tmp_path: Path) -> None:
        """Linking same child twice doesn't duplicate."""
        parent = create_window("s1")
        child = create_window("s2")

        link_child(parent, child)
        link_child(parent, child)

        meta, _ = _parse_frontmatter(parent.read_text())
        assert meta["children"].count(child.name) == 1

    def test_link_child_cross_harness(self, tmp_path: Path) -> None:
        """Relative paths across harness directories."""
        parent = create_window("s1", harness="claude-code")
        child = create_window("s2", harness="gemini")

        link_child(parent, child)

        meta, _ = _parse_frontmatter(parent.read_text())
        children = meta["children"]
        assert len(children) == 1

        # Should be a relative path containing "gemini"
        child_ref = children[0]
        assert "gemini" in child_ref

        # Verify the relative path resolves correctly
        resolved = (parent.parent / child_ref).resolve()
        assert resolved == child.resolve()


# --- find_current_window ---


class TestFindCurrentWindow:
    def test_find_current_window(self, tmp_path: Path) -> None:
        """Follows .current pointer."""
        created = create_window("my-session")
        found = find_current_window("my-session")

        assert found is not None
        assert found == created

    def test_find_current_window_missing(self) -> None:
        """Returns None when no pointer exists."""
        found = find_current_window("nonexistent")
        assert found is None

    def test_find_current_window_stale_pointer(self, tmp_path: Path) -> None:
        """Returns None when pointer exists but target file doesn't."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        pointer = directory / ".current-stale"
        pointer.write_text("nonexistent-file.md")

        found = find_current_window("stale")
        assert found is None


# --- find_latest_window ---


class TestFindLatestWindow:
    def test_find_latest_window(self, tmp_path: Path) -> None:
        """Returns most recent by timestamp."""
        # Create two windows with known filenames
        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        older = directory / "2026-03-07T10-00-00Z.md"
        older.write_text(_serialize_frontmatter({
            "parent": None,
            "children": [],
            "session_id": "s1",
            "harness": "claude-code",
            "created": "2026-03-07T10:00:00Z",
            "updated": "2026-03-07T10:00:00Z",
        }))

        newer = directory / "2026-03-07T14-00-00Z.md"
        newer.write_text(_serialize_frontmatter({
            "parent": None,
            "children": [],
            "session_id": "s2",
            "harness": "claude-code",
            "created": "2026-03-07T14:00:00Z",
            "updated": "2026-03-07T14:00:00Z",
        }))

        found = find_latest_window()
        assert found is not None
        assert found.name == "2026-03-07T14-00-00Z.md"

    def test_find_latest_window_by_session(self, tmp_path: Path) -> None:
        """Filter by session_id in frontmatter."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        # Newer file with different session
        newer = directory / "2026-03-07T14-00-00Z.md"
        newer.write_text(_serialize_frontmatter({
            "parent": None, "children": [], "session_id": "other",
            "harness": "claude-code", "created": "x", "updated": "x",
        }))

        # Older file with target session
        older = directory / "2026-03-07T10-00-00Z.md"
        older.write_text(_serialize_frontmatter({
            "parent": None, "children": [], "session_id": "target",
            "harness": "claude-code", "created": "x", "updated": "x",
        }))

        found = find_latest_window(session_id="target")
        assert found is not None
        assert found.name == "2026-03-07T10-00-00Z.md"

    def test_find_latest_window_empty(self, tmp_path: Path) -> None:
        """Returns None when no windows exist."""
        found = find_latest_window(harness="empty-harness")
        assert found is None

    def test_find_latest_window_no_session_filter(self, tmp_path: Path) -> None:
        """Without session_id, returns newest regardless of session."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        for i, (ts, sid) in enumerate([
            ("2026-03-01T10-00-00Z", "session-a"),
            ("2026-03-05T10-00-00Z", "session-b"),
            ("2026-03-03T10-00-00Z", "session-a"),
        ]):
            f = directory / f"{ts}.md"
            f.write_text(_serialize_frontmatter({
                "parent": None, "children": [], "session_id": sid,
                "harness": "claude-code", "created": "x", "updated": "x",
            }))

        found = find_latest_window()
        assert found is not None
        assert found.name == "2026-03-05T10-00-00Z.md"

    def test_find_latest_window_session_not_found(self, tmp_path: Path) -> None:
        """Returns None when no windows match the session_id."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        f = directory / "2026-03-07T10-00-00Z.md"
        f.write_text(_serialize_frontmatter({
            "parent": None, "children": [], "session_id": "other",
            "harness": "claude-code", "created": "x", "updated": "x",
        }))

        found = find_latest_window(session_id="nonexistent")
        assert found is None

    def test_find_latest_window_nonexistent_directory(self) -> None:
        """Returns None when harness directory doesn't exist."""
        found = find_latest_window(harness="does-not-exist")
        assert found is None


# --- finalized field ---


class TestFinalizedField:
    def test_create_window_has_finalized_false(self, tmp_path: Path) -> None:
        """New windows default to finalized: false."""
        path = create_window("session-fin")
        meta, _ = _parse_frontmatter(path.read_text())
        assert meta["finalized"] == "false"

    def test_create_window_with_parent_has_finalized_false(self, tmp_path: Path) -> None:
        """Child windows also default to finalized: false."""
        parent = create_window("s1")
        child = create_window("s2", parent=parent.name)
        meta, _ = _parse_frontmatter(child.read_text())
        assert meta["finalized"] == "false"


# --- CLI find-latest ---


class TestCLIFindLatest:
    def test_cli_find_latest(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI find-latest prints path to latest window file."""
        from claude_hub.continuity import main
        import sys

        directory = tmp_path / "thoughts" / "windows" / "claude-code"
        f = directory / "2026-03-07T12-00-00Z.md"
        f.write_text(_serialize_frontmatter({
            "parent": None, "children": [], "session_id": "test",
            "harness": "claude-code", "created": "x", "updated": "x",
        }))

        sys.argv = ["continuity", "find-latest", "--harness", "claude-code"]
        main()

        captured = capsys.readouterr()
        assert "2026-03-07T12-00-00Z.md" in captured.out

    def test_cli_find_latest_with_session(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI find-latest with --session-id filters correctly."""
        from claude_hub.continuity import main
        import sys

        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        for ts, sid in [
            ("2026-03-07T14-00-00Z", "other"),
            ("2026-03-07T10-00-00Z", "target"),
        ]:
            f = directory / f"{ts}.md"
            f.write_text(_serialize_frontmatter({
                "parent": None, "children": [], "session_id": sid,
                "harness": "claude-code", "created": "x", "updated": "x",
            }))

        sys.argv = ["continuity", "find-latest", "--session-id", "target"]
        main()

        captured = capsys.readouterr()
        assert "2026-03-07T10-00-00Z.md" in captured.out

    def test_cli_find_latest_no_results(self, tmp_path: Path) -> None:
        """CLI find-latest exits with code 1 when no windows found."""
        from claude_hub.continuity import main
        import sys

        sys.argv = ["continuity", "find-latest", "--harness", "nonexistent"]
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


# --- load_window_chain ---


class TestLoadWindowChain:
    def _create_chain(self, tmp_path: Path) -> list[Path]:
        """Create a 3-node chain: grandparent -> parent -> child."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        grandparent = directory / "2026-03-07T08-00-00Z.md"
        grandparent.write_text(_serialize_frontmatter({
            "parent": None,
            "children": ["2026-03-07T10-00-00Z.md"],
            "session_id": "s1",
            "harness": "claude-code",
            "created": "2026-03-07T08:00:00Z",
            "updated": "2026-03-07T08:00:00Z",
        }) + "Grandparent content.\n")

        parent = directory / "2026-03-07T10-00-00Z.md"
        parent.write_text(_serialize_frontmatter({
            "parent": "2026-03-07T08-00-00Z.md",
            "children": ["2026-03-07T12-00-00Z.md"],
            "session_id": "s1",
            "harness": "claude-code",
            "created": "2026-03-07T10:00:00Z",
            "updated": "2026-03-07T10:00:00Z",
        }) + "Parent content.\n")

        child = directory / "2026-03-07T12-00-00Z.md"
        child.write_text(_serialize_frontmatter({
            "parent": "2026-03-07T10-00-00Z.md",
            "children": [],
            "session_id": "s1",
            "harness": "claude-code",
            "created": "2026-03-07T12:00:00Z",
            "updated": "2026-03-07T12:00:00Z",
        }) + "Child content.\n")

        return [grandparent, parent, child]

    def test_load_window_chain(self, tmp_path: Path) -> None:
        """Follows parent links, respects depth limit, returns content in chronological order."""
        chain = self._create_chain(tmp_path)
        child = chain[2]

        result = load_window_chain(child, depth=3)

        # Should be in chronological order: grandparent first
        assert result.index("Grandparent content") < result.index("Parent content")
        assert result.index("Parent content") < result.index("Child content")

        # All three windows should be present
        assert "2026-03-07T08-00-00Z.md" in result
        assert "2026-03-07T10-00-00Z.md" in result
        assert "2026-03-07T12-00-00Z.md" in result

    def test_load_window_chain_depth_limit(self, tmp_path: Path) -> None:
        """Depth limit restricts how far back to traverse."""
        chain = self._create_chain(tmp_path)
        child = chain[2]

        result = load_window_chain(child, depth=1)

        # depth=1 means: child + 1 parent = parent + child
        assert "Parent content" in result
        assert "Child content" in result
        assert "Grandparent content" not in result

    def test_load_window_chain_single(self, tmp_path: Path) -> None:
        """Loading a root window returns just that window."""
        chain = self._create_chain(tmp_path)
        grandparent = chain[0]

        result = load_window_chain(grandparent, depth=3)

        assert "Grandparent content" in result
        assert "Parent content" not in result
        assert "Child content" not in result

    def test_load_window_chain_cross_harness(self, tmp_path: Path) -> None:
        """Traverses harness boundaries via relative paths."""
        cc_dir = tmp_path / "thoughts" / "windows" / "claude-code"
        gemini_dir = tmp_path / "thoughts" / "windows" / "gemini"
        gemini_dir.mkdir(parents=True)

        # Parent in gemini harness
        gemini_parent = gemini_dir / "2026-03-07T08-00-00Z.md"
        gemini_parent.write_text(_serialize_frontmatter({
            "parent": None,
            "children": [],
            "session_id": "gs1",
            "harness": "gemini",
            "created": "2026-03-07T08:00:00Z",
            "updated": "2026-03-07T08:00:00Z",
        }) + "Gemini parent content.\n")

        # Compute relative path from claude-code to gemini
        import os
        rel_parent = os.path.relpath(gemini_parent, cc_dir)

        # Child in claude-code harness with cross-harness parent
        cc_child = cc_dir / "2026-03-07T10-00-00Z.md"
        cc_child.write_text(_serialize_frontmatter({
            "parent": rel_parent,
            "children": [],
            "session_id": "cs1",
            "harness": "claude-code",
            "created": "2026-03-07T10:00:00Z",
            "updated": "2026-03-07T10:00:00Z",
        }) + "Claude child content.\n")

        # Also link the child in the parent
        link_child(gemini_parent, cc_child)

        result = load_window_chain(cc_child, depth=3)

        # Both contents should be present, gemini first (chronological)
        assert "Gemini parent content" in result
        assert "Claude child content" in result
        assert result.index("Gemini parent") < result.index("Claude child")


# --- finalize_window ---


class TestFinalizeWindow:
    def test_finalize_sets_true(self, tmp_path: Path) -> None:
        """Finalize sets finalized: true and updates timestamp."""
        path = create_window("session-fin")
        meta_before, _ = _parse_frontmatter(path.read_text())
        assert meta_before["finalized"] == "false"

        result = finalize_window(path)
        assert result is True

        meta_after, _ = _parse_frontmatter(path.read_text())
        assert meta_after["finalized"] == "true"
        # updated timestamp should have changed
        assert meta_after["updated"] >= meta_before["updated"]

    def test_finalize_idempotent(self, tmp_path: Path) -> None:
        """Finalizing an already-finalized window returns False."""
        path = create_window("session-fin2")
        finalize_window(path)

        result = finalize_window(path)
        assert result is False

    def test_finalize_nonexistent(self, tmp_path: Path) -> None:
        """Finalizing a nonexistent path returns False."""
        result = finalize_window(tmp_path / "does-not-exist.md")
        assert result is False

    def test_finalize_preserves_body(self, tmp_path: Path) -> None:
        """Finalize preserves the body content."""
        path = create_window("session-fin3")
        # Append body content
        text = path.read_text()
        path.write_text(text + "Important narrative content.\n")

        finalize_window(path)

        text_after = path.read_text()
        assert "Important narrative content." in text_after
        meta, body = _parse_frontmatter(text_after)
        assert meta["finalized"] == "true"
        assert "Important narrative content." in body


# --- create_window collision avoidance ---


class TestCreateWindowCollision:
    def test_collision_avoidance(self, tmp_path: Path) -> None:
        """When timestamp filename already exists, appends counter suffix."""
        directory = tmp_path / "thoughts" / "windows" / "claude-code"

        # Create a file that will collide with the next create_window call
        first = create_window("session-c1")
        # Manually create a file with the same timestamp to force collision
        # by using the same filename
        collider_name = first.name
        # Remove the first file's pointer so create_window doesn't reuse session
        # We need to create a second window at the "same second"
        # Simulate by pre-creating the expected filename
        from unittest.mock import patch
        from claude_hub.continuity import _timestamp_filename

        fixed_ts = first.name  # e.g. "2026-03-07T15-30-00Z.md"

        with patch("claude_hub.continuity._timestamp_filename", return_value=fixed_ts):
            second = create_window("session-c2")

        # The second file should have a -1 suffix
        assert second.name == fixed_ts.removesuffix(".md") + "-1.md"
        assert second.exists()

        # Both files should have valid frontmatter
        meta1, _ = _parse_frontmatter(first.read_text())
        meta2, _ = _parse_frontmatter(second.read_text())
        assert meta1["session_id"] == "session-c1"
        assert meta2["session_id"] == "session-c2"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        """Multiple collisions increment counter correctly."""
        from unittest.mock import patch

        first = create_window("session-m1")
        fixed_ts = first.name

        with patch("claude_hub.continuity._timestamp_filename", return_value=fixed_ts):
            second = create_window("session-m2")

        with patch("claude_hub.continuity._timestamp_filename", return_value=fixed_ts):
            third = create_window("session-m3")

        base = fixed_ts.removesuffix(".md")
        assert second.name == f"{base}-1.md"
        assert third.name == f"{base}-2.md"


# --- File locking ---


class TestFileLock:
    """_file_lock must exclude concurrent holders and keep a stable lockfile."""

    def test_lockfile_persists_after_release(self, tmp_path: Path) -> None:
        """Regression: the lockfile must NOT be unlinked on release.

        Unlinking a lockfile that other processes may be blocked on lets a
        later caller lock a fresh inode at the same path — two holders in
        the critical section at once.
        """
        from claude_hub.continuity import _file_lock

        target = tmp_path / "window.md"
        with _file_lock(target):
            pass
        lock_path = target.with_suffix(target.suffix + ".lock")
        assert lock_path.exists()

    def test_lock_excludes_second_holder_on_same_inode(self, tmp_path: Path) -> None:
        """While held, a second flock attempt on the same path must block."""
        import fcntl
        import os

        from claude_hub.continuity import _file_lock

        target = tmp_path / "window.md"
        lock_path = target.with_suffix(target.suffix + ".lock")

        with _file_lock(target):
            fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)

        # After release, the same path (same inode) is lockable again.
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
