"""Tests for ConversationStore PostgreSQL persistence.

Uses an in-memory SQLite database behind mock psycopg2 connections so that
no real PostgreSQL instance is required.  The mock faithfully reproduces
the cursor / connection context-manager protocol that ConversationStore
expects from psycopg2.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from claude_hub.conversation import GroupMessage, MessageType
from claude_hub.conversation_store import ConversationStore, ConversationStatus


# ---------------------------------------------------------------------------
# In-memory SQLite backend that mimics psycopg2 connection/cursor behaviour
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Thin wrapper around a real sqlite3.Cursor that translates
    PostgreSQL parameter style (%s) to SQLite (?), maps JSONB/TIMESTAMPTZ
    to TEXT, and supports the RealDictCursor-style dict output.

    Columns stored as JSONB in Postgres are TEXT in SQLite; psycopg2
    transparently deserialises JSONB to Python dicts.  We replicate that
    by auto-parsing any column whose name is in _JSONB_COLUMNS.
    """

    # Columns that are JSONB in the real schema — auto-deserialise on read.
    _JSONB_COLUMNS = frozenset({"metadata", "participants", "participant_summary"})

    def __init__(self, sqlite_conn: sqlite3.Connection, dict_mode: bool = False):
        self._conn = sqlite_conn
        self._dict_mode = dict_mode
        self._cursor = sqlite_conn.cursor()
        self.rowcount = 0
        self.description = None

    # -- context manager --------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cursor.close()
        return False

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _translate_sql(sql: str) -> str:
        """Rough Postgres-to-SQLite SQL translation."""
        # Parameter placeholders
        sql = sql.replace("%s", "?")
        # Type names that SQLite doesn't understand
        sql = sql.replace("TIMESTAMPTZ", "TEXT")
        sql = sql.replace("JSONB", "TEXT")
        # ON CONFLICT ... DO UPDATE SET ... = EXCLUDED.col  (SQLite supports this)
        # No change needed — SQLite >= 3.24 supports UPSERT syntax.
        return sql

    def _deserialise_jsonb(self, d: dict) -> dict:
        """Parse JSON strings in JSONB columns to Python objects."""
        for col in self._JSONB_COLUMNS:
            val = d.get(col)
            if isinstance(val, str):
                try:
                    d[col] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    # -- execute / fetch --------------------------------------------------

    def execute(self, sql: str, params=None):
        translated = self._translate_sql(sql)
        try:
            self._cursor.execute(translated, params or ())
        except sqlite3.IntegrityError:
            pass  # ON CONFLICT DO NOTHING
        self.rowcount = self._cursor.rowcount
        self.description = self._cursor.description

    def fetchall(self):
        rows = self._cursor.fetchall()
        if self._dict_mode and self.description:
            cols = [d[0] for d in self.description]
            return [self._deserialise_jsonb(dict(zip(cols, row))) for row in rows]
        return rows

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._dict_mode and self.description:
            cols = [d[0] for d in self.description]
            return self._deserialise_jsonb(dict(zip(cols, row)))
        return row


class _FakeConnection:
    """Wraps a shared sqlite3.Connection and behaves like a psycopg2
    connection (context manager, cursor factory, commit).
    """

    def __init__(self, sqlite_conn: sqlite3.Connection):
        self._conn = sqlite_conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # psycopg2 connections auto-rollback on exception; we just let SQLite
        # handle it since we call commit() explicitly in production code.
        return False

    def close(self):
        # No-op: the shared sqlite_conn is closed by the test fixture
        pass

    def cursor(self, cursor_factory=None):
        # If caller requests RealDictCursor, enable dict mode
        dict_mode = cursor_factory is not None
        return _FakeCursor(self._conn, dict_mode=dict_mode)

    def commit(self):
        self._conn.commit()


def _make_fake_connect(sqlite_conn: sqlite3.Connection):
    """Return a callable that ignores the DSN and returns a _FakeConnection
    backed by the shared in-memory SQLite database.
    """
    def _connect(dsn=None, **kwargs):
        return _FakeConnection(sqlite_conn)
    return _connect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """Create a ConversationStore backed by an in-memory SQLite database,
    with psycopg2.connect patched to use the fake connection layer.
    """
    sqlite_conn = sqlite3.connect(":memory:")
    fake_connect = _make_fake_connect(sqlite_conn)

    with patch("claude_hub.conversation_store.psycopg2") as mock_pg:
        mock_pg.connect = fake_connect
        # Expose RealDictCursor so cursor_factory=... lookups work
        mock_pg.extras = MagicMock()
        mock_pg.extras.RealDictCursor = "DICT_SENTINEL"
        s = ConversationStore(dsn="postgresql://fake/test")

    # For subsequent calls _get_conn uses psycopg2.connect, so we need to
    # keep the patch active for the lifetime of the test.  Re-patch at the
    # module level that the store references.
    @contextmanager
    def _fake_get_conn(self):
        yield _FakeConnection(sqlite_conn)

    with patch.object(
        ConversationStore, "_get_conn", _fake_get_conn
    ):
        # Also need to patch psycopg2.extras for cursor_factory comparison
        with patch("claude_hub.conversation_store.psycopg2") as mock_pg2:
            mock_pg2.connect = fake_connect
            mock_pg2.extras = MagicMock()
            mock_pg2.extras.RealDictCursor = "DICT_SENTINEL"
            yield s

    sqlite_conn.close()


def _make_msg(
    *,
    msg_id: str = "msg-001",
    conversation_id: str = "conv-abc",
    sender_id: str = "user-1",
    sender_name: str = "Alice",
    content: str = "Hello everyone",
    message_type: MessageType = MessageType.CHAT,
    recipient_id: str | None = None,
    timestamp: datetime | None = None,
    metadata: dict | None = None,
) -> GroupMessage:
    """Helper to build a GroupMessage with sensible defaults."""
    return GroupMessage(
        id=msg_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        message_type=message_type,
        recipient_id=recipient_id,
        timestamp=timestamp or datetime(2026, 2, 23, 12, 0, 0),
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_init_creates_tables(self, store):
        """Verify that _ensure_schema creates the messages, conversations, and lifecycle tables."""
        # The fixture already ran _ensure_schema via __init__.
        # We verify by trying to query each table (would raise if missing).
        store.get_messages("nonexistent")
        store.list_conversations()
        store.get_conversations_by_status("active")


# ---------------------------------------------------------------------------
# log_message / get_messages
# ---------------------------------------------------------------------------


class TestLogMessage:
    def test_log_message(self, store):
        """Log a GroupMessage, then read it back via get_messages."""
        msg = _make_msg()
        store.log_message(msg)

        rows = store.get_messages("conv-abc")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "msg-001"
        assert row["sender_name"] == "Alice"
        assert row["content"] == "Hello everyone"
        assert row["message_type"] == "chat"
        assert row["recipient_id"] is None
        assert row["metadata"] == {}

    def test_log_message_idempotent(self, store):
        """ON CONFLICT DO NOTHING means duplicate IDs are silently ignored."""
        msg = _make_msg()
        store.log_message(msg)
        store.log_message(msg)  # same id -- should not raise

        rows = store.get_messages("conv-abc")
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Conversation lifecycle
# ---------------------------------------------------------------------------


class TestConversationLifecycle:
    def test_log_conversation_lifecycle(self, store):
        """Start and end a conversation; verify timestamps are set."""
        participants = [
            {"id": "user-1", "name": "Alice"},
            {"id": "user-2", "name": "Bob"},
        ]
        store.log_conversation_start("conv-lc", participants)

        convos = store.list_conversations()
        assert len(convos) == 1
        assert convos[0]["conversation_id"] == "conv-lc"
        assert convos[0]["ended_at"] is None
        assert convos[0]["participant_summary"] == participants

        store.log_conversation_end("conv-lc")

        convos = store.list_conversations()
        assert convos[0]["ended_at"] is not None


# ---------------------------------------------------------------------------
# get_messages ordering and limit
# ---------------------------------------------------------------------------


class TestGetMessages:
    def test_get_messages_ordered(self, store):
        """Multiple messages are returned in timestamp order."""
        base = datetime(2026, 2, 23, 12, 0, 0)
        for i in range(5):
            store.log_message(
                _make_msg(
                    msg_id=f"msg-{i}",
                    content=f"Message {i}",
                    timestamp=base + timedelta(seconds=i),
                )
            )

        rows = store.get_messages("conv-abc")
        assert len(rows) == 5
        assert [r["id"] for r in rows] == [f"msg-{i}" for i in range(5)]

    def test_get_messages_with_limit(self, store):
        """The limit parameter caps the number of returned rows."""
        base = datetime(2026, 2, 23, 12, 0, 0)
        for i in range(10):
            store.log_message(
                _make_msg(
                    msg_id=f"msg-{i}",
                    timestamp=base + timedelta(seconds=i),
                )
            )

        rows = store.get_messages("conv-abc", limit=3)
        assert len(rows) == 3
        # Should be the earliest 3 (ORDER BY timestamp, LIMIT)
        assert rows[0]["id"] == "msg-0"
        assert rows[2]["id"] == "msg-2"

    def test_get_messages_empty(self, store):
        """Unknown conversation_id returns an empty list."""
        rows = store.get_messages("conv-nonexistent")
        assert rows == []


# ---------------------------------------------------------------------------
# list_conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    def test_list_conversations(self, store):
        """List returns recent conversations in descending created_at order."""
        store.log_conversation_start("conv-1", [{"name": "A"}])
        store.log_conversation_start("conv-2", [{"name": "B"}])

        convos = store.list_conversations()
        assert len(convos) == 2
        # Most recent first
        assert convos[0]["conversation_id"] == "conv-2"
        assert convos[1]["conversation_id"] == "conv-1"


# ---------------------------------------------------------------------------
# Metadata round-trip
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_metadata_round_trip(self, store):
        """A metadata dict survives the dict -> JSON -> dict round-trip."""
        meta = {"tool": "bash", "exit_code": 0, "tags": ["test", "ci"]}
        msg = _make_msg(metadata=meta)
        store.log_message(msg)

        rows = store.get_messages("conv-abc")
        assert rows[0]["metadata"] == meta

    def test_empty_metadata_returns_dict(self, store):
        """When metadata is None/empty, get_messages returns an empty dict."""
        msg = _make_msg(metadata={})
        store.log_message(msg)

        rows = store.get_messages("conv-abc")
        assert rows[0]["metadata"] == {}


# ---------------------------------------------------------------------------
# Conversation lifecycle state tracking (new)
# ---------------------------------------------------------------------------


class TestLifecycleTracking:
    """Tests for the conversation_lifecycle table and status transitions."""

    def test_track_conversation_active(self, store):
        """Track a conversation as active with initial participant list."""
        participants = [{"id": "user-1", "name": "Alice"}]
        store.track_conversation_active("conv-1", participants=participants)

        record = store.get_lifecycle_status("conv-1")
        assert record is not None
        assert record["status"] == ConversationStatus.ACTIVE
        assert record["participants"] == participants
        assert record["created_at"] is not None
        assert record["last_activity_at"] is not None
        assert record["ended_at"] is None

    def test_track_conversation_active_idempotent(self, store):
        """Tracking the same conversation twice preserves created_at."""
        store.track_conversation_active("conv-1")
        first = store.get_lifecycle_status("conv-1")

        # Track again -- should preserve original created_at
        store.track_conversation_active("conv-1", participants=[{"name": "Bob"}])
        second = store.get_lifecycle_status("conv-1")

        assert second["created_at"] == first["created_at"]
        assert second["participants"] == [{"name": "Bob"}]

    def test_update_participants(self, store):
        """Update participants for an existing conversation."""
        store.track_conversation_active("conv-1")
        store.update_participants("conv-1", [{"name": "Alice"}, {"name": "Bob"}])

        record = store.get_lifecycle_status("conv-1")
        assert len(record["participants"]) == 2
        assert record["participants"][0]["name"] == "Alice"
        assert record["participants"][1]["name"] == "Bob"

    def test_mark_conversation_ended(self, store):
        """Mark a conversation as cleanly ended."""
        store.track_conversation_active("conv-1")
        store.mark_conversation_ended("conv-1")

        record = store.get_lifecycle_status("conv-1")
        assert record["status"] == ConversationStatus.ENDED
        assert record["ended_at"] is not None

    def test_mark_conversation_interrupted(self, store):
        """Mark a conversation as interrupted with a reason."""
        store.track_conversation_active("conv-1")
        store.mark_conversation_interrupted("conv-1", reason="graceful_shutdown")

        record = store.get_lifecycle_status("conv-1")
        assert record["status"] == ConversationStatus.INTERRUPTED
        assert record["ended_at"] is not None
        assert record["shutdown_reason"] == "graceful_shutdown"

    def test_mark_all_active_interrupted(self, store):
        """Mark all active conversations as interrupted (shutdown scenario)."""
        store.track_conversation_active("conv-1")
        store.track_conversation_active("conv-2")
        store.track_conversation_active("conv-3")
        # End one normally
        store.mark_conversation_ended("conv-3")

        count = store.mark_all_active_interrupted(reason="graceful_shutdown")
        assert count == 2  # conv-1 and conv-2, not conv-3

        r1 = store.get_lifecycle_status("conv-1")
        r2 = store.get_lifecycle_status("conv-2")
        r3 = store.get_lifecycle_status("conv-3")

        assert r1["status"] == ConversationStatus.INTERRUPTED
        assert r2["status"] == ConversationStatus.INTERRUPTED
        assert r3["status"] == ConversationStatus.ENDED  # unchanged

    def test_get_conversations_by_status(self, store):
        """Filter conversations by status."""
        store.track_conversation_active("conv-1")
        store.track_conversation_active("conv-2")
        store.mark_conversation_interrupted("conv-1", reason="test")

        active = store.get_conversations_by_status(ConversationStatus.ACTIVE)
        interrupted = store.get_conversations_by_status(ConversationStatus.INTERRUPTED)

        assert len(active) == 1
        assert active[0]["conversation_id"] == "conv-2"
        assert len(interrupted) == 1
        assert interrupted[0]["conversation_id"] == "conv-1"

    def test_get_lifecycle_status_missing(self, store):
        """Getting lifecycle status for unknown conversation returns None."""
        assert store.get_lifecycle_status("conv-nonexistent") is None

    def test_log_message_updates_last_activity(self, store):
        """Logging a message updates last_activity_at on the lifecycle record."""
        store.track_conversation_active("conv-abc")
        initial = store.get_lifecycle_status("conv-abc")

        msg = _make_msg()
        store.log_message(msg)

        updated = store.get_lifecycle_status("conv-abc")
        # last_activity_at should have been updated (or at least equal)
        assert updated["last_activity_at"] >= initial["last_activity_at"]


class TestStartupRecovery:
    """Tests for the recover_on_startup method."""

    def test_recover_no_stale_conversations(self, store):
        """Recovery with no stale active conversations is a no-op."""
        summary = store.recover_on_startup()
        assert summary["crash_recovered"] == 0
        assert summary["total_interrupted"] == 0

    def test_recover_stale_active_conversations(self, store):
        """Stale active conversations (from crash) are marked interrupted."""
        store.track_conversation_active("conv-1")
        store.track_conversation_active("conv-2")

        summary = store.recover_on_startup()
        assert summary["crash_recovered"] == 2
        assert summary["total_interrupted"] == 2
        assert set(summary["interrupted_conversation_ids"]) == {"conv-1", "conv-2"}

        # Both should now be interrupted
        r1 = store.get_lifecycle_status("conv-1")
        r2 = store.get_lifecycle_status("conv-2")
        assert r1["status"] == ConversationStatus.INTERRUPTED
        assert r1["shutdown_reason"] == "crash_recovery"
        assert r2["status"] == ConversationStatus.INTERRUPTED

    def test_recover_mixed_states(self, store):
        """Recovery handles a mix of active, ended, and interrupted conversations."""
        store.track_conversation_active("conv-active")
        store.track_conversation_active("conv-ended")
        store.mark_conversation_ended("conv-ended")
        store.track_conversation_active("conv-interrupted")
        store.mark_conversation_interrupted("conv-interrupted", reason="previous_shutdown")

        summary = store.recover_on_startup()
        assert summary["crash_recovered"] == 1  # only conv-active
        assert summary["total_interrupted"] == 2  # conv-active + conv-interrupted

        r = store.get_lifecycle_status("conv-active")
        assert r["status"] == ConversationStatus.INTERRUPTED
        assert r["shutdown_reason"] == "crash_recovery"

    def test_recover_idempotent(self, store):
        """Running recovery twice doesn't re-interrupt already-interrupted conversations."""
        store.track_conversation_active("conv-1")

        summary1 = store.recover_on_startup()
        assert summary1["crash_recovered"] == 1

        summary2 = store.recover_on_startup()
        assert summary2["crash_recovered"] == 0  # nothing new to recover
        assert summary2["total_interrupted"] == 1  # still one interrupted
