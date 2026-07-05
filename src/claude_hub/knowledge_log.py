"""Append-only JSONL knowledge log for multi-agent architecture.

Concurrent conversations append tagged observations to a shared log file.
Each entry is a single JSON line with strict schema validation. The log
supports filtered reads, efficient tail access, and size-based rotation.
"""

import fcntl
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class EntryType(str, Enum):
    """Valid entry types for the knowledge log."""

    OBSERVATION = "observation"
    DECISION = "decision"
    DISCOVERY = "discovery"
    ERROR = "error"
    CHECKPOINT = "checkpoint"


# ISO 8601 UTC pattern: 2026-02-26T16:30:00Z or with fractional seconds
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
)

# Reasonable limits for string fields
_MAX_ID_LENGTH = 256
_MAX_CONTENT_LENGTH = 100_000  # 100KB of text


@dataclass
class LogEntry:
    """A single entry in the knowledge log.

    All fields except metadata are required. The timestamp must be
    ISO 8601 UTC (ending in Z). entry_type must be a valid EntryType value.
    """

    thread_id: str
    timestamp: str
    model: str
    agent_id: str
    entry_type: str
    content: str
    metadata: dict | None = None


class KnowledgeLog:
    """Append-only JSONL knowledge log with concurrent-safe writes.

    Each entry is a JSON object on its own line. Writes are atomic (file-locked).
    Reads support filtering by any combination of fields and time ranges.
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)

    def validate_entry(self, entry: LogEntry) -> list[str]:
        """Validate a LogEntry and return a list of error messages.

        Returns an empty list if the entry is valid.
        """
        errors: list[str] = []

        # Required string fields must be non-empty strings
        for field in ("thread_id", "timestamp", "model", "agent_id", "entry_type", "content"):
            value = getattr(entry, field)
            if not isinstance(value, str):
                errors.append(f"{field} must be a string, got {type(value).__name__}")
            elif not value.strip():
                errors.append(f"{field} must not be empty")

        # Length checks for ID fields
        if isinstance(entry.thread_id, str) and len(entry.thread_id) > _MAX_ID_LENGTH:
            errors.append(f"thread_id exceeds maximum length of {_MAX_ID_LENGTH}")
        if isinstance(entry.agent_id, str) and len(entry.agent_id) > _MAX_ID_LENGTH:
            errors.append(f"agent_id exceeds maximum length of {_MAX_ID_LENGTH}")
        if isinstance(entry.model, str) and len(entry.model) > _MAX_ID_LENGTH:
            errors.append(f"model exceeds maximum length of {_MAX_ID_LENGTH}")
        if isinstance(entry.content, str) and len(entry.content) > _MAX_CONTENT_LENGTH:
            errors.append(f"content exceeds maximum length of {_MAX_CONTENT_LENGTH}")

        # Timestamp must be ISO 8601 UTC
        if isinstance(entry.timestamp, str) and entry.timestamp.strip():
            if not _ISO_UTC_RE.match(entry.timestamp):
                errors.append(
                    f"timestamp must be ISO 8601 UTC (ending in Z), got '{entry.timestamp}'"
                )

        # entry_type must be a valid EntryType
        if isinstance(entry.entry_type, str) and entry.entry_type.strip():
            valid_types = {t.value for t in EntryType}
            if entry.entry_type not in valid_types:
                errors.append(
                    f"entry_type must be one of {sorted(valid_types)}, got '{entry.entry_type}'"
                )

        # metadata must be a dict or None
        if entry.metadata is not None and not isinstance(entry.metadata, dict):
            errors.append(f"metadata must be a dict or None, got {type(entry.metadata).__name__}")

        return errors

    def append(self, entry: LogEntry) -> None:
        """Validate and append a single entry to the log.

        Uses file locking (fcntl.flock) for concurrent safety. Each entry
        is written as a single JSON line terminated by a newline.

        Raises ValueError if the entry fails validation.
        """
        errors = self.validate_entry(entry)
        if errors:
            raise ValueError(f"Invalid log entry: {'; '.join(errors)}")

        data = asdict(entry)
        # Remove metadata key entirely if None for cleaner output
        if data["metadata"] is None:
            del data["metadata"]
        line = json.dumps(data, separators=(",", ":")) + "\n"

        # Ensure parent directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic append with file locking
        fd = os.open(str(self.log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def read(
        self,
        *,
        thread_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
        entry_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[LogEntry]:
        """Read log entries with optional filters.

        Args:
            thread_id: Filter by thread ID (exact match).
            agent_id: Filter by agent ID (exact match).
            model: Filter by model name (exact match).
            entry_type: Filter by entry type (exact match).
            since: Include entries at or after this ISO 8601 UTC timestamp.
            until: Include entries at or before this ISO 8601 UTC timestamp.
            limit: Maximum number of entries to return (from the end of matching results).

        Returns:
            List of matching LogEntry objects, ordered by position in the log.
        """
        if not self.log_path.exists():
            return []

        entries: list[LogEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Skip malformed lines

                # Apply filters
                if thread_id is not None and data.get("thread_id") != thread_id:
                    continue
                if agent_id is not None and data.get("agent_id") != agent_id:
                    continue
                if model is not None and data.get("model") != model:
                    continue
                if entry_type is not None and data.get("entry_type") != entry_type:
                    continue
                if since is not None and data.get("timestamp", "") < since:
                    continue
                if until is not None and data.get("timestamp", "") > until:
                    continue

                entries.append(LogEntry(
                    thread_id=data["thread_id"],
                    timestamp=data["timestamp"],
                    model=data["model"],
                    agent_id=data["agent_id"],
                    entry_type=data["entry_type"],
                    content=data["content"],
                    metadata=data.get("metadata"),
                ))

        if limit is not None:
            entries = entries[-limit:]

        return entries

    def tail(self, n: int = 10) -> list[LogEntry]:
        """Return the last N entries from the log.

        Reads from the end of the file for efficiency on large logs.
        """
        if not self.log_path.exists():
            return []

        # Read the file in reverse to find the last N lines efficiently.
        # For truly huge files a seek-from-end approach would be better,
        # but for the expected sizes (up to ~100MB before rotation) this
        # chunk-based reverse read is sufficient and correct.
        lines: list[str] = []
        chunk_size = 8192
        file_size = self.log_path.stat().st_size

        if file_size == 0:
            return []

        with open(self.log_path, "rb") as f:
            # Read chunks from the end
            remaining = file_size
            partial = b""
            while remaining > 0 and len(lines) < n + 1:
                read_size = min(chunk_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                chunk = f.read(read_size) + partial
                partial = b""

                chunk_lines = chunk.split(b"\n")
                # The first element may be a partial line if we're not at file start
                if remaining > 0:
                    partial = chunk_lines[0]
                    chunk_lines = chunk_lines[1:]

                # Prepend lines (they're in forward order within the chunk)
                lines = [l.decode("utf-8") for l in chunk_lines if l.strip()] + lines

            # If we consumed the entire file and have a leftover partial
            if remaining == 0 and partial:
                decoded = partial.decode("utf-8").strip()
                if decoded:
                    lines = [decoded] + lines

        # Take the last N lines and parse them
        tail_lines = lines[-n:]
        entries: list[LogEntry] = []
        for line in tail_lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.append(LogEntry(
                thread_id=data["thread_id"],
                timestamp=data["timestamp"],
                model=data["model"],
                agent_id=data["agent_id"],
                entry_type=data["entry_type"],
                content=data["content"],
                metadata=data.get("metadata"),
            ))
        return entries

    def rotate(self, max_size_mb: float = 100) -> Path | None:
        """Rotate the log file if it exceeds the given size.

        The current log is archived with a timestamp suffix and a fresh
        empty log is started. Returns the path to the archived file,
        or None if no rotation was needed.
        """
        if not self.log_path.exists():
            return None

        size_mb = self.log_path.stat().st_size / (1024 * 1024)
        if size_mb <= max_size_mb:
            return None

        # Generate archive filename with UTC timestamp
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"{self.log_path.stem}.{ts}{self.log_path.suffix}"
        archive_path = self.log_path.parent / archive_name

        # Rotate: move current to archive, create fresh file
        shutil.move(str(self.log_path), str(archive_path))
        self.log_path.touch()

        return archive_path

    def count(self) -> int:
        """Return the number of entries in the log."""
        if not self.log_path.exists():
            return 0

        count = 0
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
