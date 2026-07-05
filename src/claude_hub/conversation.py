"""Data structures for multi-participant group conversations.

Defines the core types for the message router: conversations, participants,
and messages. No business logic — just data classes and enums.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ParticipantType(str, Enum):
    """How a participant connects to the conversation."""
    HUMAN_WS = "human_ws"          # WebSocket connection (browser)
    CLAUDE_PROCESS = "claude_proc"  # Managed Claude Code process (stream-json pipe)
    MCP_CLIENT = "mcp_client"      # External Claude via hub_send/hub_poll
    CLI_CHAT = "cli_chat"          # External CLI (codex, gemini) — resume-per-turn


class MessageType(str, Enum):
    """Type of message in a conversation."""
    CHAT = "chat"       # Regular message
    JOIN = "join"       # Participant joined
    LEAVE = "leave"     # Participant left
    SYSTEM = "system"   # System notification


@dataclass
class GroupMessage:
    """A message in a group conversation."""
    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    content: str
    message_type: MessageType = MessageType.CHAT
    recipient_id: Optional[str] = None  # For @-directed messages
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize for WebSocket/API delivery."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "message_type": self.message_type.value,
            "recipient_id": self.recipient_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


def make_message_id() -> str:
    """Generate a unique message ID."""
    return f"msg-{uuid.uuid4().hex[:8]}"


def make_conversation_id() -> str:
    """Generate a unique conversation ID."""
    return f"conv-{uuid.uuid4().hex[:8]}"


@dataclass
class Participant:
    """A participant in a conversation."""
    participant_id: str
    name: str
    participant_type: ParticipantType
    conversation_id: str
    joined_at: datetime = field(default_factory=datetime.utcnow)

    # Transport handles — exactly one is set per participant type
    websocket: Optional[object] = None           # For HUMAN_WS (WebSocket instance)
    chat_process_id: Optional[str] = None        # For CLAUDE_PROCESS (key into ChatProcessManager)
    poll_queue: Optional[asyncio.Queue] = None   # For MCP_CLIENT
    cli_chat: Optional[object] = None            # For CLI_CHAT — any object with `async def send(prompt: str) -> str`

    # Event bus outbound queue — populated by ConversationBus dispatcher.
    # WS handler reads from this; MCP clients use poll_queue instead.
    outbound_queue: Optional[asyncio.Queue] = None

    def to_dict(self) -> dict:
        """Serialize for API/WebSocket delivery (excludes transport handles)."""
        d = {
            "participant_id": self.participant_id,
            "name": self.name,
            "participant_type": self.participant_type.value,
            "conversation_id": self.conversation_id,
            "joined_at": self.joined_at.isoformat(),
        }
        if self.cli_chat is not None:
            d["cli_kind"] = type(self.cli_chat).__name__
        return d


MAX_MESSAGE_LOG = 200


@dataclass
class Conversation:
    """A multi-participant conversation."""
    conversation_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    participants: dict[str, Participant] = field(default_factory=dict)
    message_log: list[GroupMessage] = field(default_factory=list)

    def add_participant(self, participant: Participant) -> None:
        """Add a participant to this conversation."""
        self.participants[participant.participant_id] = participant

    def remove_participant(self, participant_id: str) -> Optional[Participant]:
        """Remove and return a participant, or None if not found."""
        return self.participants.pop(participant_id, None)

    def append_message(self, message: GroupMessage) -> None:
        """Append a message, enforcing the bounded log size."""
        self.message_log.append(message)
        if len(self.message_log) > MAX_MESSAGE_LOG:
            self.message_log = self.message_log[-MAX_MESSAGE_LOG:]

    def get_participants_of_type(self, ptype: ParticipantType) -> list[Participant]:
        """Get all participants of a given type."""
        return [p for p in self.participants.values() if p.participant_type == ptype]

    def to_dict(self) -> dict:
        """Serialize for API delivery."""
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat(),
            "participants": [p.to_dict() for p in self.participants.values()],
            "message_count": len(self.message_log),
        }
