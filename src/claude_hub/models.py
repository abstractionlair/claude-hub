"""Data models for claude-hub."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Who sent the message."""
    CHAT_CLAUDE = "chat_claude"
    MAIN_CLAUDE = "main_claude"
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    """A message in a conversation between chat Claude and main Claude."""
    conversation_id: str
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InitRequest(BaseModel):
    """Request to initialize a new conversation."""
    # Chat Claude doesn't have a unique ID, so we generate one
    pass


class InitResponse(BaseModel):
    """Response to init request."""
    conversation_id: str
    status: str = "connected"
    guidance: str = Field(
        default="You're connected to Main Claude. Describe what you need—"
        "implementation, deployment, research, etc. Main Claude has full "
        "tooling, stored context, and system access. Just talk."
    )


class SendRequest(BaseModel):
    """Request to send a message to main Claude."""
    conversation_id: str
    message: str


class SendResponse(BaseModel):
    """Response from main Claude (async)."""
    conversation_id: str
    request_id: str
    status: str = "pending"  # "pending", "complete", "error"
    response: str = ""


class PollRequest(BaseModel):
    """Request to poll for a pending response."""
    request_id: str


class PollResponse(BaseModel):
    """Response from polling."""
    request_id: str
    status: str  # "pending", "complete", "error"
    response: str = ""
    conversation_id: str = ""


class RouteEntry(BaseModel):
    """Routing table entry."""
    conversation_id: str
    target: str = "main"  # "main" or sub-agent ID
    expires_after_messages: Optional[int] = None  # If set, return to main after N messages
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ControlCommand(BaseModel):
    """Control command from a Claude to modify routing."""
    command: str  # "route", "release", "escalate"
    conversation_id: Optional[str] = None
    target: Optional[str] = None
    message_count: Optional[int] = None
    escalation_message: Optional[str] = None


# --- Group Chat MCP Models ---

class GroupJoinRequest(BaseModel):
    """Request to join a group conversation via MCP."""
    conversation_id: str
    name: str

class GroupJoinResponse(BaseModel):
    """Response after joining a group conversation."""
    conversation_id: str
    participant_id: str
    participants: list[dict]
    recent_messages: list[dict]

class GroupSendRequest(BaseModel):
    """Request to send a message in a group conversation."""
    conversation_id: str
    participant_id: str
    message: str
    recipient_id: Optional[str] = None

class GroupSendResponse(BaseModel):
    """Response after sending a group message."""
    status: str = "sent"
    message_id: str

class GroupPollRequest(BaseModel):
    """Request to poll for new group messages."""
    participant_id: str
    wait_seconds: float = Field(
        default=0,
        ge=0,
        le=30,
        description="If no messages are queued, wait up to this many seconds for one to arrive before returning.",
    )

class GroupPollResponse(BaseModel):
    """Response with pending group messages."""
    messages: list[dict]

class GroupLeaveRequest(BaseModel):
    """Request to leave a group conversation."""
    conversation_id: str
    participant_id: str

class GroupLeaveResponse(BaseModel):
    """Response after leaving a group conversation."""
    status: str = "left"
