"""Tests for WorkspaceManager shared-resource permissions.

Focus: can_write_shared must fail CLOSED when a permissions metadata block
exists but cannot be read or parsed.
"""

import os
from pathlib import Path

import pytest

from claude_hub.workspace import WorkspaceManager


PROJECT = "testproj"
RESOURCE = "ontologies/schema.md"


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(base_dir=tmp_path)


def _shared_path(manager: WorkspaceManager) -> Path:
    path = manager.projects_dir / PROJECT / "shared" / RESOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


VALID_METADATA = """<!-- PERMISSIONS
created_by: work/main/
writers: [work/main/, work/main.research/]
-->

# Schema
"""


class TestGetSharedResourceMetadata:
    def test_missing_file_returns_none(self, manager):
        assert manager.get_shared_resource_metadata(PROJECT, RESOURCE) is None

    def test_file_without_block_returns_none(self, manager):
        _shared_path(manager).write_text("# Just content, no permissions\n")
        assert manager.get_shared_resource_metadata(PROJECT, RESOURCE) is None

    def test_valid_block_parsed(self, manager):
        _shared_path(manager).write_text(VALID_METADATA)
        metadata = manager.get_shared_resource_metadata(PROJECT, RESOURCE)
        assert metadata["created_by"] == "work/main/"
        assert metadata["writers"] == ["work/main/", "work/main.research/"]

    def test_unterminated_block_raises(self, manager):
        _shared_path(manager).write_text("<!-- PERMISSIONS\ncreated_by: work/main/\n")
        with pytest.raises(ValueError, match="Malformed PERMISSIONS block"):
            manager.get_shared_resource_metadata(PROJECT, RESOURCE)

    def test_undecodable_file_raises(self, manager):
        _shared_path(manager).write_bytes(b"<!-- PERMISSIONS\n\xff\xfe\x00garbage")
        with pytest.raises(ValueError, match="Cannot read"):
            manager.get_shared_resource_metadata(PROJECT, RESOURCE)


class TestCanWriteShared:
    def test_no_resource_allows_write(self, manager):
        # Creating a new shared resource is allowed.
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/main/") is True

    def test_no_metadata_allows_write(self, manager):
        _shared_path(manager).write_text("# No permissions block\n")
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/other/") is True

    def test_creator_can_write(self, manager):
        _shared_path(manager).write_text(VALID_METADATA)
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/main/") is True

    def test_listed_writer_can_write(self, manager):
        _shared_path(manager).write_text(VALID_METADATA)
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/main.research/") is True

    def test_unlisted_requester_denied(self, manager):
        _shared_path(manager).write_text(VALID_METADATA)
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/main.other/") is False

    def test_malformed_block_fails_closed(self, manager):
        # Regression: a PERMISSIONS block that exists but can't be parsed
        # must DENY, not fall through to "no metadata = anyone can write".
        _shared_path(manager).write_text("<!-- PERMISSIONS\ncreated_by: work/main/\n")
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/other/") is False

    def test_undecodable_file_fails_closed(self, manager):
        _shared_path(manager).write_bytes(b"<!-- PERMISSIONS\n\xff\xfe\x00garbage")
        assert manager.can_write_shared(PROJECT, RESOURCE, "work/other/") is False

    @pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file modes")
    def test_unreadable_file_fails_closed(self, manager):
        path = _shared_path(manager)
        path.write_text(VALID_METADATA)
        path.chmod(0o000)
        try:
            assert manager.can_write_shared(PROJECT, RESOURCE, "work/main/") is False
        finally:
            path.chmod(0o644)
