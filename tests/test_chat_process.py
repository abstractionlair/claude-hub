"""Tests for ChatProcessManager.

Tests cover:
- Priming message construction, window context loading,
  observation summary retrieval, and observation marker parsing.
- Background stdout reader: subscriber fan-out, EOF handling,
  timeout resilience, subscribe-before-write ordering.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.chat_process import ChatProcess, ChatProcessManager
from claude_hub.observations import ObservationStore, parse_observation_markers


# ---------------------------------------------------------------------------
# TestBuildPrimingMessage
# ---------------------------------------------------------------------------


class TestBuildPrimingMessage:
    @patch.object(ChatProcessManager, "_get_system_snapshot", return_value=None)
    @patch.object(ChatProcessManager, "_get_window_context", return_value=None)
    def test_minimal_prime_no_state(self, mock_window, mock_snap, tmp_path):
        """With no window context/observations/system, still includes path restrictions."""
        mgr = ChatProcessManager(
            observations_dsn="",
        )
        msg = mgr._build_priming_message()
        # Path restrictions are always included as a safety guardrail
        assert "Path Restrictions" in msg
        assert "FUSE" in msg
        assert "/storage/" in msg
        assert "orient" in msg

    @patch.object(ChatProcessManager, "_get_system_snapshot", return_value=None)
    @patch.object(ChatProcessManager, "_get_window_context", return_value=None)
    def test_with_observations(self, mock_window, mock_snap):
        """Priming message includes observations when DSN is provided."""
        from claude_hub.observations import Observation

        fake_obs = Observation(
            id="fake-id",
            created_at=datetime.now(timezone.utc).isoformat(),
            last_referenced=datetime.now(timezone.utc).isoformat(),
            category="belief",
            content="The server uses port 8420",
            tags=["infra"],
            confidence=0.9,
        )
        mock_store = MagicMock()
        mock_store.get_recent.return_value = [fake_obs]
        mock_store.format_for_context.return_value = (
            "## Loaded Observations\n\n"
            "- [belief] The server uses port 8420 (confidence: 90%)\n"
        )

        with patch("claude_hub.observations.ObservationStore", return_value=mock_store):
            mgr = ChatProcessManager(
                observations_dsn="postgresql://fake/db",
            )
            msg = mgr._build_priming_message()
            assert "orient" in msg
            assert "8420" in msg


# ---------------------------------------------------------------------------
# TestGetObservationsSummary
# ---------------------------------------------------------------------------


class TestGetObservationsSummary:
    def test_no_dsn(self):
        """With no DSN configured, observations summary returns None."""
        mgr = ChatProcessManager()
        # Force observations_dsn to empty to simulate no DB configured
        mgr.observations_dsn = ""
        assert mgr._get_observations_summary() is None

    def test_empty_db(self):
        """With DSN but no observations, summary returns None."""
        mock_store = MagicMock()
        mock_store.get_recent.return_value = []

        with patch("claude_hub.observations.ObservationStore", return_value=mock_store):
            mgr = ChatProcessManager(observations_dsn="postgresql://fake/db")
            assert mgr._get_observations_summary() is None

    def test_populated_db(self):
        """With DSN and observations, summary includes content."""
        from claude_hub.observations import Observation

        fake_obs = Observation(
            id="fake-id",
            created_at=datetime.now(timezone.utc).isoformat(),
            last_referenced=datetime.now(timezone.utc).isoformat(),
            category="codebase-fact",
            content="CLAUDE.md is loaded automatically",
            tags=["claude-code"],
            confidence=0.95,
        )
        mock_store = MagicMock()
        mock_store.get_recent.return_value = [fake_obs]
        mock_store.format_for_context.return_value = (
            "## Loaded Observations\n\n"
            "- [codebase-fact] CLAUDE.md is loaded automatically (confidence: 95%)\n"
        )

        with patch("claude_hub.observations.ObservationStore", return_value=mock_store):
            mgr = ChatProcessManager(observations_dsn="postgresql://fake/db")
            summary = mgr._get_observations_summary()
            assert summary is not None
            assert "CLAUDE.md" in summary


# ---------------------------------------------------------------------------
# TestObservationMarkerParsing
# ---------------------------------------------------------------------------


class TestObservationMarkerParsing:
    def test_parse_observe_block(self):
        """parse_observation_markers extracts [OBSERVE:...] blocks and calls store.record."""
        from claude_hub.observations import Observation

        fake_obs = Observation(
            id="fake-id",
            created_at=datetime.now(timezone.utc).isoformat(),
            last_referenced=datetime.now(timezone.utc).isoformat(),
            category="belief",
            confidence=0.8,
            content="The server binds to 0.0.0.0:8420",
            tags=["infra", "networking"],
            source_session="chat-test",
        )
        mock_store = MagicMock()
        mock_store.record.return_value = fake_obs

        text = (
            "Some preamble.\n"
            "[OBSERVE: category=belief, confidence=0.8, tags=infra, networking]\n"
            "The server binds to 0.0.0.0:8420\n"
            "[/OBSERVE]\n"
            "Some postamble."
        )
        recorded = parse_observation_markers(text, mock_store, session_id="chat-test")
        assert len(recorded) == 1
        assert recorded[0].category == "belief"
        assert recorded[0].confidence == 0.8
        assert "8420" in recorded[0].content
        assert recorded[0].source_session == "chat-test"
        mock_store.record.assert_called_once()

    def test_parse_confirm_marker(self):
        """parse_observation_markers extracts [CONFIRM:...] and calls store.confirm."""
        mock_store = MagicMock()
        mock_store.confirm.return_value = True

        text = "I verified this. [CONFIRM: abc-123-def]"
        parse_observation_markers(text, mock_store, session_id="chat-test")
        mock_store.confirm.assert_called_once_with("abc-123-def")

    def test_no_markers(self):
        """With no markers, nothing is recorded or confirmed."""
        mock_store = MagicMock()
        text = "Just a regular response with no markers at all."
        recorded = parse_observation_markers(text, mock_store, session_id="chat-test")
        assert recorded == []
        mock_store.record.assert_not_called()
        mock_store.confirm.assert_not_called()
        mock_store.refute.assert_not_called()


# ---------------------------------------------------------------------------
# TestGetChatSummary
# ---------------------------------------------------------------------------


class TestGetChatSummary:
    def test_no_process(self, tmp_path):
        mgr = ChatProcessManager()
        assert mgr.get_chat_summary("nonexistent") is None


# ---------------------------------------------------------------------------
# Helpers for async stdout reader tests
# ---------------------------------------------------------------------------


def _make_mock_process(stdout_lines: list[bytes]):
    """Create a mock asyncio.subprocess.Process with predefined stdout lines.

    Args:
        stdout_lines: Bytes to return from readline(), one per call.
            An empty b"" signals EOF.
    """
    process = MagicMock()
    process.returncode = None
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()
    process.stderr = MagicMock()

    # Build an async readline that pops from a queue
    line_queue: asyncio.Queue = asyncio.Queue()

    async def mock_readline():
        return await line_queue.get()

    process.stdout = MagicMock()
    process.stdout.readline = mock_readline
    process._line_queue = line_queue  # Expose for test to feed lines

    # Pre-load lines
    for line in stdout_lines:
        line_queue.put_nowait(line)

    process.terminate = MagicMock()
    process.kill = MagicMock()

    async def mock_wait():
        pass
    process.wait = mock_wait

    return process


def _event_line(event: dict) -> bytes:
    """Encode a dict as an NDJSON line (bytes) for mock stdout."""
    return (json.dumps(event) + "\n").encode()


# ---------------------------------------------------------------------------
# TestStdoutReader
# ---------------------------------------------------------------------------


class TestStdoutReader:
    """Tests for the decoupled background stdout reader."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_events(self):
        """Events from stdout are pushed to all subscribers."""
        events = [
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}},
            {"type": "result", "duration_ms": 100},
        ]
        process = _make_mock_process([_event_line(e) for e in events] + [b""])

        cp = ChatProcess(chat_id="test-1", process=process)
        mgr = ChatProcessManager()

        # Subscribe before starting reader
        queue = cp.subscribe("sub-1")

        # Run the reader
        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))

        # Collect events
        received = []
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            received.append(event)
            if event.get("type") in ("result", "error"):
                break

        # Should have received stream_event + result
        assert len(received) == 2
        assert received[0]["type"] == "stream_event"
        assert received[1]["type"] == "result"

        # Wait for reader to finish (EOF follows result)
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_eof_notifies_subscribers(self):
        """When stdout closes (EOF), all subscribers get an error event."""
        # EOF immediately — no events before it
        process = _make_mock_process([b""])

        cp = ChatProcess(chat_id="test-eof", process=process)
        mgr = ChatProcessManager()

        q1 = cp.subscribe("sub-1")
        q2 = cp.subscribe("sub-2")

        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

        # Both subscribers should have the error
        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1["type"] == "error"
        assert e2["type"] == "error"
        assert cp._dead is True

    @pytest.mark.asyncio
    async def test_multiple_subscribers_fan_out(self):
        """Multiple subscribers each get a copy of every event."""
        events = [
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}},
            {"type": "result", "duration_ms": 50},
        ]
        process = _make_mock_process([_event_line(e) for e in events] + [b""])

        cp = ChatProcess(chat_id="test-multi", process=process)
        mgr = ChatProcessManager()

        q1 = cp.subscribe("sub-1")
        q2 = cp.subscribe("sub-2")
        q3 = cp.subscribe("sub-3")

        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

        for q in [q1, q2, q3]:
            items = []
            while not q.empty():
                items.append(await q.get())
            # Each subscriber: stream_event + result + EOF error
            event_types = [i["type"] for i in items]
            assert "stream_event" in event_types
            assert "result" in event_types

    @pytest.mark.asyncio
    async def test_result_clears_busy_flag(self):
        """The background reader clears cp.busy when it sees a result event."""
        events = [
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}}},
            {"type": "result", "duration_ms": 10},
        ]
        process = _make_mock_process([_event_line(e) for e in events] + [b""])

        cp = ChatProcess(chat_id="test-busy", process=process)
        cp.busy = True
        mgr = ChatProcessManager()

        cp.subscribe("sub-1")

        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

        assert cp.busy is False

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        """After unsubscribe, no more events are delivered to that queue."""
        process = _make_mock_process([])  # We'll feed lines manually

        cp = ChatProcess(chat_id="test-unsub", process=process)
        mgr = ChatProcessManager()

        q1 = cp.subscribe("sub-1")
        q2 = cp.subscribe("sub-2")

        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))

        # Feed first event
        event1 = {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}}
        process._line_queue.put_nowait(_event_line(event1))

        # Both should get it
        e1 = await asyncio.wait_for(q1.get(), timeout=2.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=2.0)
        assert e1["type"] == "stream_event"
        assert e2["type"] == "stream_event"

        # Unsubscribe q1
        cp.unsubscribe("sub-1")

        # Feed second event
        event2 = {"type": "result", "duration_ms": 10}
        process._line_queue.put_nowait(_event_line(event2))

        # q2 should get it
        e2 = await asyncio.wait_for(q2.get(), timeout=2.0)
        assert e2["type"] == "result"

        # q1 should NOT have it
        assert q1.empty()

        # Clean up
        process._line_queue.put_nowait(b"")  # EOF
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_timeout_does_not_corrupt_reader(self):
        """A subscriber timeout doesn't affect the background reader or other subscribers."""
        process = _make_mock_process([])  # Manual feed

        cp = ChatProcess(chat_id="test-timeout", process=process)
        mgr = ChatProcessManager()

        q_slow = cp.subscribe("slow")
        q_fast = cp.subscribe("fast")

        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))

        # Simulate: q_slow times out waiting (nothing comes for a while)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q_slow.get(), timeout=0.1)

        # Unsubscribe the slow one (as send_message would do after timeout)
        cp.unsubscribe("slow")

        # Now feed events — fast subscriber should still work fine
        event = {"type": "result", "duration_ms": 10}
        process._line_queue.put_nowait(_event_line(event))

        e = await asyncio.wait_for(q_fast.get(), timeout=2.0)
        assert e["type"] == "result"

        # Reader is still alive
        assert not cp._reader_task.done()
        assert not cp._dead

        # Clean up
        process._line_queue.put_nowait(b"")
        await asyncio.wait_for(cp._reader_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_send_message_integration(self):
        """send_message subscribes, writes, yields, and unsubscribes correctly."""
        events = [
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}},
            {"type": "result", "duration_ms": 200, "session_id": "sess-123"},
        ]
        process = _make_mock_process([_event_line(e) for e in events] + [b""])

        cp = ChatProcess(chat_id="test-send", process=process)
        mgr = ChatProcessManager()
        mgr._processes["test-send"] = cp

        # Start the background reader
        cp._reader_task = asyncio.create_task(mgr._stdout_reader(cp))

        # Use send_message — it should subscribe, write, yield events, unsubscribe
        received = []
        async for event in mgr.send_message("test-send", "hi"):
            received.append(event)

        assert len(received) == 2
        assert received[0]["type"] == "stream_event"
        assert received[1]["type"] == "result"

        # Subscriber should be cleaned up
        assert len(cp._subscribers) == 0

        # Wait for reader to finish
        await asyncio.wait_for(cp._reader_task, timeout=2.0)
