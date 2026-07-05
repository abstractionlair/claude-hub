"""Tests for the append-only JSONL knowledge log."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_hub.knowledge_log import EntryType, KnowledgeLog, LogEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def log_path(tmp_path) -> Path:
    """Return a path for a temporary knowledge log file."""
    return tmp_path / "knowledge.jsonl"


@pytest.fixture
def log(log_path) -> KnowledgeLog:
    """Create a KnowledgeLog backed by a temporary file."""
    return KnowledgeLog(log_path=log_path)


def _make_entry(
    *,
    thread_id: str = "thread-001",
    timestamp: str = "2026-02-26T16:30:00Z",
    model: str = "claude-opus-4-6",
    agent_id: str = "main-claude",
    entry_type: str = "observation",
    content: str = "Test observation",
    metadata: dict | None = None,
) -> LogEntry:
    """Helper to build a LogEntry with sensible defaults."""
    return LogEntry(
        thread_id=thread_id,
        timestamp=timestamp,
        model=model,
        agent_id=agent_id,
        entry_type=entry_type,
        content=content,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_entry_no_errors(self, log):
        """A well-formed entry produces no validation errors."""
        entry = _make_entry()
        errors = log.validate_entry(entry)
        assert errors == []

    def test_valid_entry_with_metadata(self, log):
        """An entry with metadata dict validates cleanly."""
        entry = _make_entry(metadata={"tags": ["test"], "severity": "low"})
        errors = log.validate_entry(entry)
        assert errors == []

    def test_valid_entry_all_types(self, log):
        """Every defined EntryType value is accepted."""
        for et in EntryType:
            entry = _make_entry(entry_type=et.value)
            errors = log.validate_entry(entry)
            assert errors == [], f"entry_type '{et.value}' should be valid"

    def test_empty_thread_id(self, log):
        """Empty thread_id is rejected."""
        entry = _make_entry(thread_id="")
        errors = log.validate_entry(entry)
        assert any("thread_id" in e for e in errors)

    def test_whitespace_only_field(self, log):
        """Whitespace-only strings are rejected as empty."""
        entry = _make_entry(agent_id="   ")
        errors = log.validate_entry(entry)
        assert any("agent_id" in e for e in errors)

    def test_invalid_entry_type(self, log):
        """An unrecognized entry_type is rejected."""
        entry = _make_entry(entry_type="thought")
        errors = log.validate_entry(entry)
        assert any("entry_type" in e for e in errors)

    def test_invalid_timestamp_format(self, log):
        """A non-ISO-8601-UTC timestamp is rejected."""
        entry = _make_entry(timestamp="2026-02-26 16:30:00")
        errors = log.validate_entry(entry)
        assert any("timestamp" in e for e in errors)

    def test_timestamp_without_z(self, log):
        """A timestamp with offset instead of Z is rejected."""
        entry = _make_entry(timestamp="2026-02-26T16:30:00+00:00")
        errors = log.validate_entry(entry)
        assert any("timestamp" in e for e in errors)

    def test_timestamp_with_fractional_seconds(self, log):
        """A timestamp with fractional seconds and Z is accepted."""
        entry = _make_entry(timestamp="2026-02-26T16:30:00.123456Z")
        errors = log.validate_entry(entry)
        assert errors == []

    def test_metadata_wrong_type(self, log):
        """metadata must be dict or None, not a list."""
        entry = _make_entry(metadata=["not", "a", "dict"])  # type: ignore[arg-type]
        errors = log.validate_entry(entry)
        assert any("metadata" in e for e in errors)

    def test_thread_id_too_long(self, log):
        """Excessively long thread_id is rejected."""
        entry = _make_entry(thread_id="x" * 300)
        errors = log.validate_entry(entry)
        assert any("thread_id" in e and "length" in e for e in errors)

    def test_agent_id_too_long(self, log):
        """Excessively long agent_id is rejected."""
        entry = _make_entry(agent_id="x" * 300)
        errors = log.validate_entry(entry)
        assert any("agent_id" in e and "length" in e for e in errors)

    def test_content_too_long(self, log):
        """Excessively long content is rejected."""
        entry = _make_entry(content="x" * 200_000)
        errors = log.validate_entry(entry)
        assert any("content" in e and "length" in e for e in errors)

    def test_multiple_errors_reported(self, log):
        """Multiple validation failures are all reported."""
        entry = _make_entry(thread_id="", entry_type="invalid", timestamp="bad")
        errors = log.validate_entry(entry)
        assert len(errors) >= 3

    def test_append_rejects_invalid_entry(self, log):
        """append() raises ValueError for an invalid entry."""
        entry = _make_entry(entry_type="invalid")
        with pytest.raises(ValueError, match="Invalid log entry"):
            log.append(entry)


# ---------------------------------------------------------------------------
# Append and read roundtrip
# ---------------------------------------------------------------------------


class TestAppendRead:
    def test_append_and_read_single(self, log):
        """A single appended entry can be read back."""
        entry = _make_entry()
        log.append(entry)

        entries = log.read()
        assert len(entries) == 1
        assert entries[0].thread_id == "thread-001"
        assert entries[0].model == "claude-opus-4-6"
        assert entries[0].content == "Test observation"

    def test_append_multiple(self, log):
        """Multiple entries are read back in order."""
        for i in range(5):
            log.append(_make_entry(
                thread_id=f"thread-{i:03d}",
                timestamp=f"2026-02-26T16:{i:02d}:00Z",
                content=f"Entry {i}",
            ))

        entries = log.read()
        assert len(entries) == 5
        assert entries[0].thread_id == "thread-000"
        assert entries[4].thread_id == "thread-004"

    def test_metadata_roundtrip(self, log):
        """Metadata survives the dict -> JSON -> dict roundtrip."""
        meta = {"tags": ["review", "architecture"], "pr": 42, "nested": {"key": "val"}}
        log.append(_make_entry(metadata=meta))

        entries = log.read()
        assert entries[0].metadata == meta

    def test_metadata_none_roundtrip(self, log):
        """An entry with None metadata reads back as None."""
        log.append(_make_entry(metadata=None))

        entries = log.read()
        assert entries[0].metadata is None

    def test_unicode_content(self, log):
        """Unicode content survives the roundtrip."""
        content = "Race condition in \u2192 message_router \U0001f914"
        log.append(_make_entry(content=content))

        entries = log.read()
        assert entries[0].content == content

    def test_creates_parent_directory(self, tmp_path):
        """The log creates parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "log.jsonl"
        klog = KnowledgeLog(log_path=deep_path)
        klog.append(_make_entry())

        assert deep_path.exists()
        assert klog.count() == 1

    def test_jsonl_format(self, log, log_path):
        """Each entry is a single line of valid JSON."""
        log.append(_make_entry(content="first"))
        log.append(_make_entry(content="second"))

        raw_lines = log_path.read_text("utf-8").strip().split("\n")
        assert len(raw_lines) == 2
        for line in raw_lines:
            data = json.loads(line)
            assert "thread_id" in data
            assert "content" in data


# ---------------------------------------------------------------------------
# Filtered reading
# ---------------------------------------------------------------------------


class TestFilteredRead:
    @pytest.fixture(autouse=True)
    def _populate(self, log):
        """Populate the log with diverse entries for filter tests."""
        entries = [
            _make_entry(
                thread_id="thread-a",
                timestamp="2026-02-26T10:00:00Z",
                model="claude-opus-4-6",
                agent_id="main-claude",
                entry_type="observation",
                content="First obs",
            ),
            _make_entry(
                thread_id="thread-b",
                timestamp="2026-02-26T11:00:00Z",
                model="gemini-2.5-pro",
                agent_id="reviewer",
                entry_type="discovery",
                content="Found race condition",
            ),
            _make_entry(
                thread_id="thread-a",
                timestamp="2026-02-26T12:00:00Z",
                model="claude-opus-4-6",
                agent_id="main-claude",
                entry_type="decision",
                content="Decided to fix routing",
            ),
            _make_entry(
                thread_id="thread-c",
                timestamp="2026-02-26T13:00:00Z",
                model="codex-gpt-5.1",
                agent_id="builder",
                entry_type="error",
                content="Build failed",
            ),
            _make_entry(
                thread_id="thread-b",
                timestamp="2026-02-26T14:00:00Z",
                model="gemini-2.5-pro",
                agent_id="reviewer",
                entry_type="checkpoint",
                content="Review complete",
            ),
        ]
        for e in entries:
            log.append(e)

    def test_filter_by_thread_id(self, log):
        """Filter returns only entries for the specified thread."""
        entries = log.read(thread_id="thread-a")
        assert len(entries) == 2
        assert all(e.thread_id == "thread-a" for e in entries)

    def test_filter_by_agent_id(self, log):
        """Filter returns only entries for the specified agent."""
        entries = log.read(agent_id="reviewer")
        assert len(entries) == 2
        assert all(e.agent_id == "reviewer" for e in entries)

    def test_filter_by_model(self, log):
        """Filter returns only entries for the specified model."""
        entries = log.read(model="gemini-2.5-pro")
        assert len(entries) == 2
        assert all(e.model == "gemini-2.5-pro" for e in entries)

    def test_filter_by_entry_type(self, log):
        """Filter returns only entries of the specified type."""
        entries = log.read(entry_type="error")
        assert len(entries) == 1
        assert entries[0].content == "Build failed"

    def test_filter_by_since(self, log):
        """since filter includes entries at and after the timestamp."""
        entries = log.read(since="2026-02-26T12:00:00Z")
        assert len(entries) == 3
        assert entries[0].timestamp == "2026-02-26T12:00:00Z"

    def test_filter_by_until(self, log):
        """until filter includes entries at and before the timestamp."""
        entries = log.read(until="2026-02-26T11:00:00Z")
        assert len(entries) == 2
        assert entries[-1].timestamp == "2026-02-26T11:00:00Z"

    def test_filter_by_since_and_until(self, log):
        """Combined since/until gives a time range."""
        entries = log.read(since="2026-02-26T11:00:00Z", until="2026-02-26T13:00:00Z")
        assert len(entries) == 3

    def test_filter_with_limit(self, log):
        """limit returns only the last N matching entries."""
        entries = log.read(limit=2)
        assert len(entries) == 2
        # Should be the last two entries
        assert entries[0].content == "Build failed"
        assert entries[1].content == "Review complete"

    def test_combined_filters(self, log):
        """Multiple filters are ANDed together."""
        entries = log.read(agent_id="main-claude", entry_type="observation")
        assert len(entries) == 1
        assert entries[0].content == "First obs"

    def test_filter_no_match(self, log):
        """Filters that match nothing return an empty list."""
        entries = log.read(thread_id="nonexistent")
        assert entries == []


# ---------------------------------------------------------------------------
# Tail
# ---------------------------------------------------------------------------


class TestTail:
    def test_tail_default(self, log):
        """tail() returns the last 10 entries (or all if fewer)."""
        for i in range(5):
            log.append(_make_entry(content=f"Entry {i}"))

        entries = log.tail()
        assert len(entries) == 5
        assert entries[-1].content == "Entry 4"

    def test_tail_with_n(self, log):
        """tail(n) returns exactly the last n entries."""
        for i in range(20):
            log.append(_make_entry(
                content=f"Entry {i}",
                timestamp=f"2026-02-26T{i:02d}:00:00Z",
            ))

        entries = log.tail(n=3)
        assert len(entries) == 3
        assert entries[0].content == "Entry 17"
        assert entries[1].content == "Entry 18"
        assert entries[2].content == "Entry 19"

    def test_tail_more_than_available(self, log):
        """Requesting more entries than exist returns all entries."""
        for i in range(3):
            log.append(_make_entry(content=f"Entry {i}"))

        entries = log.tail(n=100)
        assert len(entries) == 3

    def test_tail_empty_log(self, log):
        """tail() on a nonexistent log returns an empty list."""
        entries = log.tail()
        assert entries == []

    def test_tail_single_entry(self, log):
        """tail() works correctly with a single entry."""
        log.append(_make_entry(content="Only one"))
        entries = log.tail(n=1)
        assert len(entries) == 1
        assert entries[0].content == "Only one"


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


class TestCount:
    def test_count_empty(self, log):
        """count() returns 0 for nonexistent log."""
        assert log.count() == 0

    def test_count_after_appends(self, log):
        """count() returns the number of entries appended."""
        for i in range(7):
            log.append(_make_entry(content=f"Entry {i}"))
        assert log.count() == 7


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


class TestRotation:
    def test_no_rotation_below_threshold(self, log):
        """rotate() returns None when the file is below the size limit."""
        log.append(_make_entry(content="small"))
        result = log.rotate(max_size_mb=100)
        assert result is None

    def test_no_rotation_nonexistent(self, log):
        """rotate() returns None when the log doesn't exist."""
        result = log.rotate()
        assert result is None

    def test_rotation_above_threshold(self, log, log_path):
        """rotate() archives the file when it exceeds the size limit."""
        # Write enough data to exceed a tiny threshold
        for i in range(100):
            log.append(_make_entry(content=f"Observation number {i}: " + "x" * 200))

        archive = log.rotate(max_size_mb=0.001)  # ~1KB threshold

        assert archive is not None
        assert archive.exists()
        assert archive.parent == log_path.parent
        assert archive.suffix == ".jsonl"

        # The original path should now be an empty file
        assert log_path.exists()
        assert log_path.stat().st_size == 0

        # The archive should contain the old data
        archive_lines = archive.read_text("utf-8").strip().split("\n")
        assert len(archive_lines) == 100

    def test_rotation_preserves_data(self, log, log_path):
        """No data is lost during rotation."""
        for i in range(50):
            log.append(_make_entry(content=f"Entry {i}"))

        original_count = log.count()
        archive = log.rotate(max_size_mb=0.001)
        assert archive is not None

        # Count entries in archive
        archive_lines = [l for l in archive.read_text("utf-8").strip().split("\n") if l.strip()]
        assert len(archive_lines) == original_count

        # New log is empty, ready for new appends
        assert log.count() == 0

    def test_append_after_rotation(self, log):
        """Appends work normally after rotation."""
        for i in range(50):
            log.append(_make_entry(content=f"Before {i}"))

        log.rotate(max_size_mb=0.001)

        log.append(_make_entry(content="After rotation"))
        assert log.count() == 1
        entries = log.read()
        assert entries[0].content == "After rotation"


# ---------------------------------------------------------------------------
# Concurrent append safety
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_appends(self, log):
        """Multiple threads appending concurrently produce no data loss."""
        num_threads = 10
        entries_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def worker(thread_idx):
            barrier.wait()  # Synchronize thread start for maximum contention
            for i in range(entries_per_thread):
                log.append(_make_entry(
                    thread_id=f"thread-{thread_idx}",
                    content=f"Thread {thread_idx} entry {i}",
                    timestamp=f"2026-02-26T{thread_idx:02d}:{i:02d}:00Z",
                ))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every entry should be present
        total = log.count()
        assert total == num_threads * entries_per_thread

        # Verify each thread's entries are all present
        for thread_idx in range(num_threads):
            entries = log.read(thread_id=f"thread-{thread_idx}")
            assert len(entries) == entries_per_thread

    def test_concurrent_lines_not_interleaved(self, log, log_path):
        """Each line in the file is a complete, parseable JSON object."""
        num_threads = 5
        entries_per_thread = 20
        barrier = threading.Barrier(num_threads)

        def worker(thread_idx):
            barrier.wait()
            for i in range(entries_per_thread):
                log.append(_make_entry(
                    thread_id=f"t-{thread_idx}",
                    content=f"Content from thread {thread_idx} iteration {i}",
                ))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every line must be valid JSON
        raw = log_path.read_text("utf-8")
        lines = [l for l in raw.strip().split("\n") if l.strip()]
        assert len(lines) == num_threads * entries_per_thread
        for i, line in enumerate(lines):
            try:
                data = json.loads(line)
                assert "thread_id" in data
                assert "content" in data
            except json.JSONDecodeError:
                pytest.fail(f"Line {i} is not valid JSON: {line[:100]}...")


# ---------------------------------------------------------------------------
# Empty log handling
# ---------------------------------------------------------------------------


class TestEmptyLog:
    def test_read_empty(self, log):
        """read() on a nonexistent log returns an empty list."""
        entries = log.read()
        assert entries == []

    def test_tail_empty(self, log):
        """tail() on a nonexistent log returns an empty list."""
        entries = log.tail()
        assert entries == []

    def test_count_empty(self, log):
        """count() on a nonexistent log returns 0."""
        assert log.count() == 0

    def test_read_empty_file(self, log, log_path):
        """read() on an existing but empty file returns an empty list."""
        log_path.touch()
        entries = log.read()
        assert entries == []

    def test_tail_empty_file(self, log, log_path):
        """tail() on an existing but empty file returns an empty list."""
        log_path.touch()
        entries = log.tail()
        assert entries == []


# ---------------------------------------------------------------------------
# Large entry handling
# ---------------------------------------------------------------------------


class TestLargeEntries:
    def test_large_content_within_limit(self, log):
        """Content up to the max length is accepted."""
        large_content = "x" * 90_000  # Under 100KB limit
        log.append(_make_entry(content=large_content))

        entries = log.read()
        assert len(entries) == 1
        assert len(entries[0].content) == 90_000

    def test_large_metadata(self, log):
        """Large metadata dicts survive the roundtrip."""
        meta = {f"key_{i}": f"value_{i}" * 50 for i in range(100)}
        log.append(_make_entry(metadata=meta))

        entries = log.read()
        assert entries[0].metadata == meta

    def test_many_entries_count(self, log):
        """A log with many entries counts correctly."""
        n = 500
        for i in range(n):
            log.append(_make_entry(
                content=f"Entry {i}",
                timestamp=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
            ))
        assert log.count() == n


# ---------------------------------------------------------------------------
# EntryType enum
# ---------------------------------------------------------------------------


class TestEntryTypeEnum:
    def test_all_values(self):
        """EntryType enum contains all expected values."""
        expected = {"observation", "decision", "discovery", "error", "checkpoint"}
        actual = {t.value for t in EntryType}
        assert actual == expected

    def test_string_enum(self):
        """EntryType values are usable as plain strings."""
        assert EntryType.OBSERVATION == "observation"
        assert EntryType.DECISION == "decision"
