"""Tests for the multi-participant message router.

Tests cover:
- Conversation data structures (create, add/remove participants, bounded log)
- GroupMessage creation and serialization
- make_message_id uniqueness
- MessageRouter with mocked transports (WebSocket, ChatProcessManager)
- ConversationBus event-driven message routing
- Conversation lifecycle state tracking and shutdown resilience
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.conversation import (
    MAX_MESSAGE_LOG,
    Conversation,
    GroupMessage,
    MessageType,
    Participant,
    ParticipantType,
    make_conversation_id,
    make_message_id,
)
from claude_hub.message_router import ConversationBus, MessageRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_participant(
    pid: str = "p-1",
    name: str = "Alice",
    ptype: ParticipantType = ParticipantType.HUMAN_WS,
    conv_id: str = "conv-test",
    **kwargs,
) -> Participant:
    """Create a Participant with sensible defaults."""
    return Participant(
        participant_id=pid,
        name=name,
        participant_type=ptype,
        conversation_id=conv_id,
        **kwargs,
    )


def make_group_message(
    conv_id: str = "conv-test",
    sender_id: str = "p-1",
    sender_name: str = "Alice",
    content: str = "Hello everyone",
    **kwargs,
) -> GroupMessage:
    """Create a GroupMessage with sensible defaults."""
    return GroupMessage(
        id=make_message_id(),
        conversation_id=conv_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        **kwargs,
    )


def make_mock_websocket() -> AsyncMock:
    """Create a mock WebSocket with send_json."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def make_mock_cpm() -> MagicMock:
    """Create a mock ChatProcessManager with the methods used by MessageRouter."""
    cpm = MagicMock()
    cpm.get_or_spawn = AsyncMock()
    cpm.send_message = AsyncMock()
    cpm.write_message = AsyncMock()
    cpm.kill_process = AsyncMock()
    cpm._processes = {}
    cpm._build_priming_message = MagicMock(return_value="Ready. Respond with just: ok")
    return cpm


# ---------------------------------------------------------------------------
# TestConversation
# ---------------------------------------------------------------------------


class TestConversation:
    def test_create_conversation(self):
        conv = Conversation(conversation_id="conv-1")
        assert conv.conversation_id == "conv-1"
        assert conv.participants == {}
        assert conv.message_log == []

    def test_add_participant(self):
        conv = Conversation(conversation_id="conv-1")
        p = make_participant(pid="alice", name="Alice", conv_id="conv-1")
        conv.add_participant(p)
        assert "alice" in conv.participants
        assert conv.participants["alice"].name == "Alice"

    def test_add_multiple_participants(self):
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(make_participant(pid="alice", name="Alice", conv_id="conv-1"))
        conv.add_participant(make_participant(pid="bob", name="Bob", conv_id="conv-1"))
        conv.add_participant(
            make_participant(
                pid="claude-1",
                name="Claude",
                ptype=ParticipantType.CLAUDE_PROCESS,
                conv_id="conv-1",
            )
        )
        assert len(conv.participants) == 3

    def test_remove_participant(self):
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(make_participant(pid="alice", name="Alice", conv_id="conv-1"))
        removed = conv.remove_participant("alice")
        assert removed is not None
        assert removed.name == "Alice"
        assert "alice" not in conv.participants

    def test_remove_nonexistent_participant(self):
        conv = Conversation(conversation_id="conv-1")
        removed = conv.remove_participant("ghost")
        assert removed is None

    def test_get_participants_of_type(self):
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(make_participant(pid="a", name="Alice", conv_id="conv-1"))
        conv.add_participant(make_participant(pid="b", name="Bob", conv_id="conv-1"))
        conv.add_participant(
            make_participant(
                pid="c", name="Claude", ptype=ParticipantType.CLAUDE_PROCESS, conv_id="conv-1"
            )
        )
        humans = conv.get_participants_of_type(ParticipantType.HUMAN_WS)
        claudes = conv.get_participants_of_type(ParticipantType.CLAUDE_PROCESS)
        assert len(humans) == 2
        assert len(claudes) == 1
        assert claudes[0].name == "Claude"

    def test_list_participants_via_to_dict(self):
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(make_participant(pid="alice", name="Alice", conv_id="conv-1"))
        d = conv.to_dict()
        assert d["conversation_id"] == "conv-1"
        assert len(d["participants"]) == 1
        assert d["participants"][0]["name"] == "Alice"
        assert d["message_count"] == 0

    def test_bounded_message_log(self):
        """Message log is bounded to MAX_MESSAGE_LOG entries."""
        conv = Conversation(conversation_id="conv-1")
        for i in range(MAX_MESSAGE_LOG + 50):
            conv.append_message(
                make_group_message(
                    conv_id="conv-1",
                    content=f"Message {i}",
                )
            )
        assert len(conv.message_log) == MAX_MESSAGE_LOG
        # The oldest messages should have been dropped
        assert "Message 50" in conv.message_log[0].content
        assert f"Message {MAX_MESSAGE_LOG + 49}" in conv.message_log[-1].content

    def test_append_message_below_limit(self):
        """When below the limit, all messages are retained."""
        conv = Conversation(conversation_id="conv-1")
        for i in range(10):
            conv.append_message(make_group_message(conv_id="conv-1", content=f"Msg {i}"))
        assert len(conv.message_log) == 10
        assert conv.message_log[0].content == "Msg 0"


# ---------------------------------------------------------------------------
# TestGroupMessage
# ---------------------------------------------------------------------------


class TestGroupMessage:
    def test_creation_defaults(self):
        msg = GroupMessage(
            id="msg-001",
            conversation_id="conv-1",
            sender_id="alice",
            sender_name="Alice",
            content="Hello!",
        )
        assert msg.message_type == MessageType.CHAT
        assert msg.recipient_id is None
        assert msg.metadata == {}
        assert msg.timestamp is not None

    def test_to_dict_serialization(self):
        msg = GroupMessage(
            id="msg-002",
            conversation_id="conv-1",
            sender_id="alice",
            sender_name="Alice",
            content="Test content",
            message_type=MessageType.JOIN,
            recipient_id="bob",
            metadata={"key": "value"},
        )
        d = msg.to_dict()
        assert d["id"] == "msg-002"
        assert d["conversation_id"] == "conv-1"
        assert d["sender_id"] == "alice"
        assert d["sender_name"] == "Alice"
        assert d["content"] == "Test content"
        assert d["message_type"] == "join"
        assert d["recipient_id"] == "bob"
        assert d["metadata"] == {"key": "value"}
        # Timestamp should be ISO-format string
        assert isinstance(d["timestamp"], str)
        assert "T" in d["timestamp"]

    def test_to_dict_none_recipient(self):
        msg = make_group_message()
        d = msg.to_dict()
        assert d["recipient_id"] is None


# ---------------------------------------------------------------------------
# TestMakeMessageId
# ---------------------------------------------------------------------------


class TestMakeMessageId:
    def test_has_prefix(self):
        mid = make_message_id()
        assert mid.startswith("msg-")

    def test_uniqueness(self):
        ids = {make_message_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_format(self):
        mid = make_message_id()
        # msg- prefix + 8 hex chars
        assert len(mid) == 4 + 8  # "msg-" + 8


class TestMakeConversationId:
    def test_has_prefix(self):
        cid = make_conversation_id()
        assert cid.startswith("conv-")

    def test_uniqueness(self):
        ids = {make_conversation_id() for _ in range(1000)}
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# TestMessageRouter
# ---------------------------------------------------------------------------


class TestMessageRouter:
    def test_create_conversation(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        conv = router.create_conversation("conv-test")
        assert conv.conversation_id == "conv-test"
        assert router.get_conversation("conv-test") is conv
        # Bus should be created
        assert "conv-test" in router._buses

    def test_create_conversation_auto_id(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        conv = router.create_conversation()
        assert conv.conversation_id.startswith("conv-")

    def test_get_or_create_conversation(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        conv1 = router.get_or_create_conversation("conv-1")
        conv2 = router.get_or_create_conversation("conv-1")
        assert conv1 is conv2

    def test_list_conversations(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-a")
        router.create_conversation("conv-b")
        convs = router.list_conversations()
        assert len(convs) == 2
        ids = {c["conversation_id"] for c in convs}
        assert ids == {"conv-a", "conv-b"}

    def test_add_human(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        p = router.add_human("conv-1", "Alice", ws)
        assert p.name == "Alice"
        assert p.participant_type == ParticipantType.HUMAN_WS
        assert p.websocket is ws
        assert p.participant_id == "human-alice"

    def test_add_human_custom_id(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        p = router.add_human("conv-1", "Alice", ws, participant_id="custom-alice")
        assert p.participant_id == "custom-alice"

    def test_add_human_to_missing_conversation(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        with pytest.raises(ValueError, match="not found"):
            router.add_human("nonexistent", "Alice", make_mock_websocket())

    @pytest.mark.asyncio
    async def test_add_claude_process(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        p = await router.add_claude_process("conv-1", "Helper")
        assert p.name == "Helper"
        assert p.participant_type == ParticipantType.CLAUDE_PROCESS
        assert p.chat_process_id == "group-conv-1-claude-helper"
        # CPM.get_or_spawn should have been called with the chat_id and priming
        cpm.get_or_spawn.assert_called_once()
        call_args = cpm.get_or_spawn.call_args
        assert call_args[0][0] == "group-conv-1-claude-helper"

    @pytest.mark.asyncio
    async def test_add_claude_to_missing_conversation(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        with pytest.raises(ValueError, match="not found"):
            await router.add_claude_process("nonexistent", "Helper")

    def test_remove_participant_cleans_up_index(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)
        # Verify participant is indexed
        assert "human-alice" in router._participant_index
        # Remove
        removed = router.remove_participant("human-alice")
        assert removed is not None
        assert removed.name == "Alice"
        # Index should be cleaned up
        assert "human-alice" not in router._participant_index
        # Conversation should no longer have the participant
        conv = router.get_conversation("conv-1")
        assert "human-alice" not in conv.participants

    def test_remove_nonexistent_participant(self):
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        result = router.remove_participant("ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_post_message_returns_group_message(self):
        """post_message creates and returns a GroupMessage."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        msg = await router.post_message("human-alice", "Hello from Alice")
        assert msg is not None
        assert msg.sender_name == "Alice"
        assert msg.content == "Hello from Alice"

    @pytest.mark.asyncio
    async def test_post_message_unknown_sender_returns_none(self):
        """post_message returns None for unknown sender."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        result = await router.post_message("ghost", "Hello?")
        assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self):
        """subscribe returns an outbound queue for the participant."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        q = router.subscribe("human-alice")
        assert q is not None
        assert isinstance(q, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_group_priming_includes_participant_list(self):
        """Group priming message includes the names of current participants."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")

        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)
        router.add_human("conv-1", "Bob", make_mock_websocket(), participant_id="human-bob")

        # Now add a Claude -- priming should mention Alice and Bob
        await router.add_claude_process("conv-1", "Helper")

        # Check what get_or_spawn was called with
        call_args = cpm.get_or_spawn.call_args
        priming_message = call_args[1].get("priming_message") or call_args[0][1]
        assert "Alice" in priming_message
        assert "Bob" in priming_message
        assert "Helper" in priming_message
        assert "group conversation" in priming_message.lower()

    @pytest.mark.asyncio
    async def test_group_priming_includes_recent_messages(self):
        """Group priming includes recent message history."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        conv = router.create_conversation("conv-1")

        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        # Add some messages to the conversation before the Claude joins
        conv.append_message(
            make_group_message(
                conv_id="conv-1",
                sender_id="human-alice",
                sender_name="Alice",
                content="Let's discuss the architecture",
            )
        )
        conv.append_message(
            make_group_message(
                conv_id="conv-1",
                sender_id="human-alice",
                sender_name="Alice",
                content="I think we need microservices",
            )
        )

        await router.add_claude_process("conv-1", "Architect")

        call_args = cpm.get_or_spawn.call_args
        priming_message = call_args[1].get("priming_message") or call_args[0][1]
        assert "architecture" in priming_message
        assert "microservices" in priming_message

    @pytest.mark.asyncio
    async def test_cleanup_conversation(self):
        """cleanup_conversation kills Claude processes and cleans up state."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")

        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)
        await router.add_claude_process("conv-1", "Helper")

        assert "human-alice" in router._participant_index
        assert "claude-helper" in router._participant_index

        await router.cleanup_conversation("conv-1")

        # Conversation should be gone
        assert router.get_conversation("conv-1") is None
        # Bus should be gone
        assert "conv-1" not in router._buses
        # Participant index should be cleaned up
        assert "human-alice" not in router._participant_index
        assert "claude-helper" not in router._participant_index
        # CPM kill should have been called for the Claude process
        cpm.kill_process.assert_called_once_with("group-conv-1-claude-helper")

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_conversation(self):
        """cleanup_conversation is a no-op for unknown conversation IDs."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        # Should not raise
        await router.cleanup_conversation("nonexistent")

    @pytest.mark.asyncio
    async def test_shutdown_cleans_all_conversations(self):
        """shutdown removes all conversations."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        router.create_conversation("conv-2")

        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)
        await router.add_claude_process("conv-2", "Helper")

        await router.shutdown()

        assert len(router._conversations) == 0
        assert len(router._participant_index) == 0
        assert len(router._buses) == 0

    def test_add_mcp_client(self):
        """add_mcp_client creates participant with poll_queue."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")
        p = router.add_mcp_client("conv-1", "Excel Claude")
        assert p.name == "Excel Claude"
        assert p.participant_type == ParticipantType.MCP_CLIENT
        assert p.poll_queue is not None
        assert p.participant_id == "mcp-excel-claude"
        assert "mcp-excel-claude" in router._participant_index

    def test_add_mcp_client_to_missing_conversation(self):
        """add_mcp_client raises ValueError for nonexistent conversation."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        with pytest.raises(ValueError, match="not found"):
            router.add_mcp_client("nonexistent", "Excel Claude")

    @pytest.mark.asyncio
    async def test_add_claude_process_main_role(self):
        """Main role spawns in project_dir with role-specific priming."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")

        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        p = await router.add_claude_process("conv-1", "Main Claude", role="main")
        assert p.name == "Main Claude"
        assert p.participant_type == ParticipantType.CLAUDE_PROCESS

        # CPM.get_or_spawn should have been called with cwd=project_dir
        call_args = cpm.get_or_spawn.call_args
        assert call_args[1].get("cwd") == cpm.project_dir or call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("cwd") is not None

        # Priming should include Main Claude role identity
        priming = call_args[1].get("priming_message") or call_args[0][1]
        assert "Main Claude" in priming
        assert "window file" in priming.lower()

    @pytest.mark.asyncio
    async def test_add_claude_process_chat_role_default(self):
        """Default chat role spawns without cwd override."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm)
        router.create_conversation("conv-1")

        await router.add_claude_process("conv-1", "Helper")

        call_args = cpm.get_or_spawn.call_args
        # Default role should pass cwd=None
        assert call_args[1].get("cwd") is None


# ---------------------------------------------------------------------------
# TestConversationBus
# ---------------------------------------------------------------------------


class TestConversationBus:
    """Tests for the event-driven ConversationBus."""

    @pytest.mark.asyncio
    async def test_post_message_echoes_to_sender(self):
        """Sender sees own message in their outbound queue."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")

        await bus.post_message("human-alice", "Hello")

        # Sender should see their own message echoed
        event = await asyncio.wait_for(alice_q.get(), timeout=1.0)
        assert event["type"] == "group_message"
        assert event["sender_name"] == "Alice"
        assert event["content"] == "Hello"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_post_message_delivers_to_other_humans(self):
        """Other humans get group_message via their outbound queue."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        conv.add_participant(
            make_participant(pid="human-bob", name="Bob", conv_id="conv-1")
        )
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        bob_q = bus.subscribe("human-bob")

        await bus.post_message("human-alice", "Hello Bob")

        # Give dispatcher time to process
        await asyncio.sleep(0.05)

        # Bob should receive the message via dispatcher
        event = await asyncio.wait_for(bob_q.get(), timeout=1.0)
        assert event["type"] == "group_message"
        assert event["sender_name"] == "Alice"
        assert event["content"] == "Hello Bob"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_post_message_delivers_to_mcp(self):
        """MCP poll_queue gets the message."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        poll_queue = asyncio.Queue()
        conv.add_participant(
            make_participant(
                pid="mcp-client-1",
                name="External",
                ptype=ParticipantType.MCP_CLIENT,
                conv_id="conv-1",
                poll_queue=poll_queue,
            )
        )
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")

        await bus.post_message("human-alice", "Hello MCP")

        # Give dispatcher time to process
        await asyncio.sleep(0.05)

        # MCP client should have the message in its poll queue
        msg = await asyncio.wait_for(poll_queue.get(), timeout=1.0)
        assert msg["type"] == "group_message"
        assert msg["content"] == "Hello MCP"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_claude_receives_formatted_message(self):
        """Claude process receives [From name] formatted message via cpm.write_message."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        # Create a mock ChatProcess with subscribe/unsubscribe
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=asyncio.Queue())
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")
        await bus.register_claude(claude_p)

        await bus.post_message("human-alice", "What is 2+2?")

        # Give writer time to pick up from delivery queue
        await asyncio.sleep(0.2)

        # cpm.write_message should have been called with formatted text
        cpm.write_message.assert_called_once()
        call_args = cpm.write_message.call_args
        assert call_args[0][0] == chat_id
        assert call_args[0][1] == "[From Alice] What is 2+2?"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_claude_response_flows_to_inbox(self):
        """Claude response posted back through bus inbox."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        # Create a subscriber queue we control
        subscriber_queue = asyncio.Queue()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=subscriber_queue)
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        await bus.register_claude(claude_p)

        # Simulate Claude streaming response
        await subscriber_queue.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "The answer is 4"},
            },
        })
        await subscriber_queue.put({
            "type": "result",
            "duration_ms": 100,
            "session_id": "sess-1",
        })

        # Give listener + dispatcher time to fully process
        await asyncio.sleep(0.2)

        # Drain all events from alice_q at once
        events = []
        while not alice_q.empty():
            events.append(alice_q.get_nowait())

        group_msgs = [e for e in events if e.get("type") == "group_message"]
        stream_events = [e for e in events if e.get("type", "").startswith("stream_")]

        # No streaming in group chat — Alice gets the final group_message
        assert len(stream_events) == 0
        assert len(group_msgs) >= 1
        assert group_msgs[0]["content"] == "The answer is 4"
        assert group_msgs[0]["sender_name"] == "Helper"
        assert len(conv.message_log) >= 1

        await bus.stop()

    @pytest.mark.asyncio
    async def test_claude_response_delivered_to_humans(self):
        """After Claude responds, all humans (except claude sender) see it."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        conv.add_participant(
            make_participant(pid="human-bob", name="Bob", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        subscriber_queue = asyncio.Queue()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=subscriber_queue)
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        bob_q = bus.subscribe("human-bob")
        await bus.register_claude(claude_p)

        # Simulate Claude response
        await subscriber_queue.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hello humans"},
            },
        })
        await subscriber_queue.put({
            "type": "result",
            "duration_ms": 100,
            "session_id": "sess-1",
        })

        # Give time for processing
        await asyncio.sleep(0.2)

        # Both Alice and Bob should see the stream chunks (via broadcast)
        alice_events = []
        while not alice_q.empty():
            alice_events.append(alice_q.get_nowait())

        bob_events = []
        while not bob_q.empty():
            bob_events.append(bob_q.get_nowait())

        # No streaming in group chat — both humans get the final group_message
        alice_msgs = [e for e in alice_events if e.get("type") == "group_message"]
        bob_msgs = [e for e in bob_events if e.get("type") == "group_message"]
        assert len(alice_msgs) >= 1
        assert len(bob_msgs) >= 1

        await bus.stop()

    @pytest.mark.asyncio
    async def test_all_messages_route_to_claudes(self):
        """All messages route to Claude processes regardless of origin."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=asyncio.Queue())
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")
        await bus.register_claude(claude_p)

        # Multiple messages all reach Claude
        await bus.post_message("human-alice", "First")
        await bus.post_message("human-alice", "Second")
        await asyncio.sleep(0.3)
        assert cpm.write_message.call_count == 2

        await bus.stop()

    @pytest.mark.asyncio
    async def test_directed_message_only_to_target(self):
        """Directed messages (recipient_id) only go to the target participant."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        conv.add_participant(
            make_participant(pid="human-bob", name="Bob", conv_id="conv-1")
        )
        conv.add_participant(
            make_participant(pid="human-charlie", name="Charlie", conv_id="conv-1")
        )

        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        bob_q = bus.subscribe("human-bob")
        charlie_q = bus.subscribe("human-charlie")

        # Alice sends directed message to Bob only
        await bus.post_message("human-alice", "Hey Bob", recipient_id="human-bob")

        # Give dispatcher time
        await asyncio.sleep(0.05)

        # Alice should see echo
        alice_event = await asyncio.wait_for(alice_q.get(), timeout=1.0)
        assert alice_event["type"] == "group_message"

        # Bob should receive
        bob_event = await asyncio.wait_for(bob_q.get(), timeout=1.0)
        assert bob_event["type"] == "group_message"
        assert bob_event["content"] == "Hey Bob"

        # Charlie should NOT receive
        assert charlie_q.empty()

        await bus.stop()

    @pytest.mark.asyncio
    async def test_streaming_chunks_accumulated_not_broadcast(self):
        """Stream chunks are accumulated silently and delivered as final group_message."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        conv.add_participant(
            make_participant(pid="human-bob", name="Bob", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        subscriber_queue = asyncio.Queue()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=subscriber_queue)
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        bob_q = bus.subscribe("human-bob")
        await bus.register_claude(claude_p)

        # Simulate streaming from Claude
        await subscriber_queue.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "chunk1"},
            },
        })
        await subscriber_queue.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "chunk2"},
            },
        })
        await subscriber_queue.put({
            "type": "result",
            "duration_ms": 50,
            "session_id": "s",
        })

        await asyncio.sleep(0.1)

        # No streaming — chunks are accumulated and delivered as group_message
        alice_events = []
        while not alice_q.empty():
            alice_events.append(alice_q.get_nowait())
        bob_events = []
        while not bob_q.empty():
            bob_events.append(bob_q.get_nowait())

        alice_stream = [e for e in alice_events if e.get("type", "").startswith("stream_")]
        bob_stream = [e for e in bob_events if e.get("type", "").startswith("stream_")]
        assert len(alice_stream) == 0
        assert len(bob_stream) == 0

        alice_msgs = [e for e in alice_events if e.get("type") == "group_message"]
        bob_msgs = [e for e in bob_events if e.get("type") == "group_message"]
        assert len(alice_msgs) == 1
        assert len(bob_msgs) == 1
        assert alice_msgs[0]["content"] == "chunk1chunk2"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_error_in_claude_doesnt_crash_bus(self):
        """Bus keeps running after an error in one Claude process."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        # Make write_message raise an error
        cpm.write_message = AsyncMock(side_effect=Exception("Process died"))

        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=asyncio.Queue())
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        await bus.register_claude(claude_p)

        # Post a message -- Claude writer should hit an error
        await bus.post_message("human-alice", "Hello")
        await asyncio.sleep(0.2)

        # Bus dispatcher should still be running -- post another message
        await bus.post_message("human-alice", "Still here?")
        await asyncio.sleep(0.05)

        # Alice should still get events from the bus
        events = []
        while not alice_q.empty():
            events.append(alice_q.get_nowait())

        # Should have at least the echo events for both messages
        group_msgs = [e for e in events if e.get("type") == "group_message"]
        assert len(group_msgs) >= 2

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_claudes_all_respond(self):
        """All Claude processes get the message when sent to inbox."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        claude_ids = []
        for name_suffix in ["A", "B", "C"]:
            chat_id = f"group-conv-1-claude-claude-{name_suffix.lower()}"
            claude_ids.append(chat_id)
            claude_p = make_participant(
                pid=f"claude-claude-{name_suffix.lower()}",
                name=f"Claude-{name_suffix}",
                ptype=ParticipantType.CLAUDE_PROCESS,
                conv_id="conv-1",
                chat_process_id=chat_id,
            )
            conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        for chat_id in claude_ids:
            mock_cp = MagicMock()
            mock_cp.busy = False
            mock_cp._dead = False
            mock_cp.subscribe = MagicMock(return_value=asyncio.Queue())
            mock_cp.unsubscribe = MagicMock()
            cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")
        for name_suffix in ["A", "B", "C"]:
            pid = f"claude-claude-{name_suffix.lower()}"
            p = conv.participants[pid]
            await bus.register_claude(p)

        await bus.post_message("human-alice", "Hello all")

        # Give writer tasks time to pick up and write
        await asyncio.sleep(0.3)

        # All three Claude processes should have received a write_message call
        assert cpm.write_message.call_count == 3
        called_ids = {call[0][0] for call in cpm.write_message.call_args_list}
        assert called_ids == set(claude_ids)

        # All should have received the formatted message
        for call in cpm.write_message.call_args_list:
            assert call[0][1] == "[From Alice] Hello all"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_message_logged_to_conversation(self):
        """Messages posted through the bus are logged to the conversation message_log."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")

        await bus.post_message("human-alice", "Test message")

        # Give dispatcher time to append to log
        await asyncio.sleep(0.05)

        assert len(conv.message_log) == 1
        assert conv.message_log[0].content == "Test message"
        assert conv.message_log[0].sender_name == "Alice"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_all_tasks(self):
        """stop() cleanly cancels dispatcher and claude tasks."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=asyncio.Queue())
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()
        await bus.register_claude(claude_p)

        # Verify tasks are running
        assert bus._dispatcher_task is not None
        assert len(bus._claude_tasks) == 1

        await bus.stop()

        # All tasks should be cleaned up
        assert bus._dispatcher_task is None
        assert len(bus._claude_tasks) == 0
        assert len(bus._outbound) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self):
        """unsubscribe removes the outbound queue."""
        conv = Conversation(conversation_id="conv-1")
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)

        bus.subscribe("pid-1")
        assert "pid-1" in bus._outbound

        bus.unsubscribe("pid-1")
        assert "pid-1" not in bus._outbound

    @pytest.mark.asyncio
    async def test_claude_cascading(self):
        """Claude A's response is delivered to Claude B (symmetric routing)."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id_a = "group-conv-1-claude-a"
        claude_a = make_participant(
            pid="claude-a",
            name="Claude-A",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id_a,
        )
        conv.add_participant(claude_a)

        chat_id_b = "group-conv-1-claude-b"
        claude_b = make_participant(
            pid="claude-b",
            name="Claude-B",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id_b,
        )
        conv.add_participant(claude_b)

        cpm = make_mock_cpm()

        sub_a = asyncio.Queue()
        mock_cp_a = MagicMock()
        mock_cp_a.busy = False
        mock_cp_a._dead = False
        mock_cp_a.subscribe = MagicMock(return_value=sub_a)
        mock_cp_a.unsubscribe = MagicMock()
        cpm._processes[chat_id_a] = mock_cp_a

        sub_b = asyncio.Queue()
        mock_cp_b = MagicMock()
        mock_cp_b.busy = False
        mock_cp_b._dead = False
        mock_cp_b.subscribe = MagicMock(return_value=sub_b)
        mock_cp_b.unsubscribe = MagicMock()
        cpm._processes[chat_id_b] = mock_cp_b

        bus = ConversationBus(conv, cpm)
        await bus.start()

        bus.subscribe("human-alice")
        await bus.register_claude(claude_a)
        await bus.register_claude(claude_b)

        # Human sends message -- both Claudes should get it
        await bus.post_message("human-alice", "Hello")
        await asyncio.sleep(0.3)
        assert cpm.write_message.call_count == 2

        # Simulate Claude A responding -- should flow to Claude B
        await sub_a.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Reply from A"},
            },
        })
        await sub_a.put({
            "type": "result",
            "duration_ms": 50,
            "session_id": "s",
        })

        await asyncio.sleep(0.5)

        # Claude B should have received Claude A's response
        b_writes = [
            call for call in cpm.write_message.call_args_list
            if call[0][0] == chat_id_b
        ]
        assert len(b_writes) >= 2  # initial + Claude A's response

        await bus.stop()

    @pytest.mark.asyncio
    async def test_broadcast_to_outbound(self):
        """_broadcast_to_outbound puts event in all outbound queues."""
        conv = Conversation(conversation_id="conv-1")
        cpm = make_mock_cpm()
        bus = ConversationBus(conv, cpm)

        q1 = bus.subscribe("p1")
        q2 = bus.subscribe("p2")
        q3 = bus.subscribe("p3")

        event = {"type": "test_event", "data": "hello"}
        bus._broadcast_to_outbound(event)

        assert q1.get_nowait() == event
        assert q2.get_nowait() == event
        assert q3.get_nowait() == event

    @pytest.mark.asyncio
    async def test_pass_response_filtered(self):
        """PASS responses from Claude are silently consumed — no inbox post, no group_message."""
        conv = Conversation(conversation_id="conv-1")
        conv.add_participant(
            make_participant(pid="human-alice", name="Alice", conv_id="conv-1")
        )

        chat_id = "group-conv-1-claude-helper"
        claude_p = make_participant(
            pid="claude-helper",
            name="Helper",
            ptype=ParticipantType.CLAUDE_PROCESS,
            conv_id="conv-1",
            chat_process_id=chat_id,
        )
        conv.add_participant(claude_p)

        cpm = make_mock_cpm()
        subscriber_queue = asyncio.Queue()
        mock_cp = MagicMock()
        mock_cp.busy = False
        mock_cp._dead = False
        mock_cp.subscribe = MagicMock(return_value=subscriber_queue)
        mock_cp.unsubscribe = MagicMock()
        cpm._processes[chat_id] = mock_cp

        bus = ConversationBus(conv, cpm)
        await bus.start()

        alice_q = bus.subscribe("human-alice")
        await bus.register_claude(claude_p)

        # Simulate Claude streaming "PASS" response
        await subscriber_queue.put({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "PASS"},
            },
        })
        await subscriber_queue.put({
            "type": "result",
            "duration_ms": 50,
            "session_id": "sess-1",
        })

        # Give listener + dispatcher time to process
        await asyncio.sleep(0.2)

        # Drain all events from alice's queue
        events = []
        while not alice_q.empty():
            events.append(alice_q.get_nowait())

        # No streaming in group chat — PASS is silently consumed.
        # Alice should see nothing at all.
        group_msgs = [e for e in events if e.get("type") == "group_message"]
        stream_events = [e for e in events if e.get("type", "").startswith("stream_")]

        assert len(stream_events) == 0  # no streaming in group chat
        assert len(group_msgs) == 0  # PASS filtered — no group_message

        # Conversation message log should NOT contain the PASS
        pass_msgs = [m for m in conv.message_log if m.content.strip().upper() == "PASS"]
        assert len(pass_msgs) == 0

        await bus.stop()


# ---------------------------------------------------------------------------
# TestMessageRouterLifecycle
# ---------------------------------------------------------------------------


class InMemoryConversationStore:
    """In-memory fake of ConversationStore for testing (no PostgreSQL needed)."""

    def __init__(self):
        self._conversations = {}   # conv_id -> {created_at, ended_at, participant_summary}
        self._lifecycle = {}       # conv_id -> {conversation_id, status, participants, created_at, ended_at, last_activity_at, shutdown_reason}
        self._messages = []

    def log_message(self, msg) -> None:
        from datetime import datetime, timezone
        self._messages.append(msg)
        rec = self._lifecycle.get(msg.conversation_id)
        if rec:
            rec["last_activity_at"] = datetime.now(timezone.utc).isoformat()

    def log_conversation_start(self, conversation_id, participants) -> None:
        from datetime import datetime, timezone
        self._conversations[conversation_id] = {
            "conversation_id": conversation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "participant_summary": participants,
        }

    def log_conversation_end(self, conversation_id) -> None:
        from datetime import datetime, timezone
        rec = self._conversations.get(conversation_id)
        if rec:
            rec["ended_at"] = datetime.now(timezone.utc).isoformat()

    def get_messages(self, conversation_id, limit=None):
        msgs = [m for m in self._messages if m.conversation_id == conversation_id]
        if limit:
            msgs = msgs[:limit]
        return msgs

    def track_conversation_active(self, conversation_id, participants=None) -> None:
        from datetime import datetime, timezone
        import json
        now = datetime.now(timezone.utc).isoformat()
        self._lifecycle[conversation_id] = {
            "conversation_id": conversation_id,
            "status": "active",
            "participants": participants or [],
            "created_at": now,
            "ended_at": None,
            "last_activity_at": now,
            "shutdown_reason": None,
        }

    def update_participants(self, conversation_id, participants) -> None:
        from datetime import datetime, timezone
        rec = self._lifecycle.get(conversation_id)
        if rec:
            rec["participants"] = participants
            rec["last_activity_at"] = datetime.now(timezone.utc).isoformat()

    def mark_conversation_ended(self, conversation_id) -> None:
        from datetime import datetime, timezone
        rec = self._lifecycle.get(conversation_id)
        if rec:
            now = datetime.now(timezone.utc).isoformat()
            rec["status"] = "ended"
            rec["ended_at"] = now
            rec["last_activity_at"] = now

    def mark_conversation_interrupted(self, conversation_id, reason="shutdown") -> None:
        from datetime import datetime, timezone
        rec = self._lifecycle.get(conversation_id)
        if rec:
            now = datetime.now(timezone.utc).isoformat()
            rec["status"] = "interrupted"
            rec["ended_at"] = now
            rec["last_activity_at"] = now
            rec["shutdown_reason"] = reason

    def mark_all_active_interrupted(self, reason="shutdown") -> int:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for rec in self._lifecycle.values():
            if rec["status"] == "active":
                rec["status"] = "interrupted"
                rec["ended_at"] = now
                rec["last_activity_at"] = now
                rec["shutdown_reason"] = reason
                count += 1
        return count

    def get_conversations_by_status(self, status):
        return [dict(rec) for rec in self._lifecycle.values() if rec["status"] == status]

    def get_lifecycle_status(self, conversation_id):
        rec = self._lifecycle.get(conversation_id)
        if rec is None:
            return None
        return dict(rec)

    def recover_on_startup(self):
        stale_active = self.get_conversations_by_status("active")
        crash_count = 0
        if stale_active:
            crash_count = self.mark_all_active_interrupted(reason="crash_recovery")
        interrupted = self.get_conversations_by_status("interrupted")
        return {
            "crash_recovered": crash_count,
            "total_interrupted": len(interrupted),
            "interrupted_conversation_ids": [c["conversation_id"] for c in interrupted],
        }


class TestMessageRouterLifecycle:
    """Tests for conversation lifecycle tracking through the MessageRouter."""

    @pytest.fixture
    def store(self):
        """Create an in-memory ConversationStore fake (no PostgreSQL needed)."""
        return InMemoryConversationStore()

    @pytest.fixture
    def router_with_store(self, store):
        """Create a MessageRouter with a real ConversationStore."""
        cpm = make_mock_cpm()
        return MessageRouter(cpm, store=store), store

    def test_create_conversation_tracks_active(self, router_with_store):
        """Creating a conversation marks it active in lifecycle table."""
        router, store = router_with_store
        router.create_conversation("conv-1")

        record = store.get_lifecycle_status("conv-1")
        assert record is not None
        assert record["status"] == "active"

    def test_add_human_updates_participants(self, router_with_store):
        """Adding a human updates the participant list in lifecycle table."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        record = store.get_lifecycle_status("conv-1")
        assert len(record["participants"]) == 1
        assert record["participants"][0]["name"] == "Alice"

    def test_add_mcp_client_updates_participants(self, router_with_store):
        """Adding an MCP client updates the participant list in lifecycle table."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        router.add_mcp_client("conv-1", "External")

        record = store.get_lifecycle_status("conv-1")
        assert len(record["participants"]) == 1
        assert record["participants"][0]["name"] == "External"

    @pytest.mark.asyncio
    async def test_add_claude_updates_participants(self, router_with_store):
        """Adding a Claude process updates the participant list in lifecycle table."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        await router.add_claude_process("conv-1", "Helper")

        record = store.get_lifecycle_status("conv-1")
        assert len(record["participants"]) == 1
        assert record["participants"][0]["name"] == "Helper"

    def test_multiple_participants_tracked(self, router_with_store):
        """Multiple participants are all tracked in the lifecycle record."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        ws1 = make_mock_websocket()
        ws2 = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws1)
        router.add_human("conv-1", "Bob", ws2, participant_id="human-bob")
        router.add_mcp_client("conv-1", "External")

        record = store.get_lifecycle_status("conv-1")
        assert len(record["participants"]) == 3
        names = {p["name"] for p in record["participants"]}
        assert names == {"Alice", "Bob", "External"}

    @pytest.mark.asyncio
    async def test_cleanup_marks_conversation_ended(self, router_with_store):
        """cleanup_conversation marks lifecycle status as ended."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        await router.cleanup_conversation("conv-1")

        record = store.get_lifecycle_status("conv-1")
        assert record["status"] == "ended"
        assert record["ended_at"] is not None

    @pytest.mark.asyncio
    async def test_shutdown_marks_all_interrupted(self, router_with_store):
        """Graceful shutdown marks all active conversations as interrupted."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        router.create_conversation("conv-2")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        await router.shutdown()

        r1 = store.get_lifecycle_status("conv-1")
        r2 = store.get_lifecycle_status("conv-2")
        assert r1["status"] == "interrupted"
        assert r1["shutdown_reason"] == "graceful_shutdown"
        assert r2["status"] == "interrupted"
        assert r2["shutdown_reason"] == "graceful_shutdown"

    @pytest.mark.asyncio
    async def test_shutdown_does_not_affect_ended_conversations(self, router_with_store):
        """Shutdown only interrupts active conversations, not already-ended ones."""
        router, store = router_with_store
        router.create_conversation("conv-1")
        router.create_conversation("conv-2")

        # End conv-1 normally
        await router.cleanup_conversation("conv-1")

        # Now shutdown
        await router.shutdown()

        r1 = store.get_lifecycle_status("conv-1")
        r2 = store.get_lifecycle_status("conv-2")
        assert r1["status"] == "ended"  # unchanged
        assert r2["status"] == "interrupted"

    def test_startup_recovery_no_stale(self, router_with_store):
        """Startup recovery with no stale conversations is a no-op."""
        router, store = router_with_store
        summary = router.startup_recovery()
        assert summary["crash_recovered"] == 0

    def test_startup_recovery_detects_crash(self, router_with_store):
        """Startup recovery detects conversations left active from a crash."""
        router, store = router_with_store

        # Simulate previous run: create conversations that were never cleaned up
        store.track_conversation_active("conv-old-1")
        store.track_conversation_active("conv-old-2")

        summary = router.startup_recovery()
        assert summary["crash_recovered"] == 2
        assert summary["total_interrupted"] == 2

        r1 = store.get_lifecycle_status("conv-old-1")
        assert r1["status"] == "interrupted"
        assert r1["shutdown_reason"] == "crash_recovery"

    @pytest.mark.asyncio
    async def test_full_lifecycle_flow(self, router_with_store):
        """Full lifecycle: create -> add participants -> send messages -> shutdown -> recover."""
        router, store = router_with_store

        # Phase 1: Create and populate
        router.create_conversation("conv-1")
        ws = make_mock_websocket()
        router.add_human("conv-1", "Alice", ws)

        record = store.get_lifecycle_status("conv-1")
        assert record["status"] == "active"
        assert len(record["participants"]) == 1

        # Phase 2: Graceful shutdown
        await router.shutdown()
        record = store.get_lifecycle_status("conv-1")
        assert record["status"] == "interrupted"
        assert record["shutdown_reason"] == "graceful_shutdown"

        # Phase 3: New instance starts up and recovers
        cpm2 = make_mock_cpm()
        router2 = MessageRouter(cpm2, store=store)
        summary = router2.startup_recovery()

        # The graceful_shutdown conversations are already interrupted,
        # so crash_recovered should be 0 (they weren't left as "active")
        assert summary["crash_recovered"] == 0
        assert summary["total_interrupted"] == 1

    def test_startup_recovery_without_store(self):
        """Startup recovery without a store returns empty summary."""
        cpm = make_mock_cpm()
        router = MessageRouter(cpm, store=None)
        summary = router.startup_recovery()
        assert summary["crash_recovered"] == 0
        assert summary["total_interrupted"] == 0
